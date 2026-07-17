"""Servicio de importación del reporte ERP de despachos.

ÚNICA puerta de escritura de órdenes / líneas / catálogo / eventos (patrón del
inventario). `importar_reporte` es **idempotente**: recargar el mismo archivo no
cambia nada. Los datos ERP se refrescan en cada carga; las marcas locales de
trabajo (estado de alistamiento/despacho, alertas y cambios de material) JAMÁS
se pisan desde el archivo.

Rendimiento: una sola `transaction.atomic()` con operaciones en bloque
(`in_bulk` + `bulk_create`/`bulk_update`), sin SELECTs por orden. El parseo del
archivo (~26 MB) ocurre FUERA de la transacción de escritura.
"""
import unicodedata
from collections import defaultdict, deque
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import (ArticuloERP, CargaReporte, EventoOrden, LineaOrden,
                     OrdenDespacho)
from .reporte import parsear_reporte


class ReporteViejo(Exception):
    """El archivo subido es MÁS viejo que la última carga (su `max(Fecha orden)`
    es ESTRICTAMENTE menor) → se rechaza para no pisar datos frescos con datos
    caducos. Igual máximo = recarga del mismo día, se acepta. Las vistas la
    traducen a `messages.error`."""


class TransicionInvalida(Exception):
    """Acción de estado o de cambio de material no permitida para el estado
    actual de la orden/línea (p. ej. despachar una orden que no está alistada, o
    cambiar el material de una orden ya cerrada en el ERP). Las vistas la
    traducen a `messages.error`."""


# Campos "espejo ERP" de la orden: se copian tal cual desde la primera fila del
# grupo (idénticos en todas las líneas de la orden) en cada carga.
_CAMPOS_ERP = (
    'sucursal', 'centro_costos', 'bodega', 'estado_orden_erp',
    'estado_facturacion', 'vigencia', 'cliente', 'id_cliente', 'telefono',
    'departamento', 'ciudad', 'direccion', 'vendedor', 'observacion',
    'fecha_entrega', 'fecha_orden',
)

# Campos que el import puede tocar de una orden existente (ERP + denormalizaciones
# + los de estado que fija el cierre/alerta). Es la lista de `bulk_update`.
_CAMPOS_UPDATE = _CAMPOS_ERP + (
    'es_despachable', 'n_lineas', 'resumen_articulos',
    'estado', 'cerrada_en', 'cerrada_sin_marcar', 'alerta_remision',
)

# Campos de una línea que refresca el import (los de cambio de material NO están:
# son marcas locales que sobreviven porque viven en la MISMA fila).
_CAMPOS_LINEA_UPDATE = ('articulo', 'cod_articulo', 'descripcion', 'categoria',
                        'cantidad', 'es_material', 'orden_archivo', 'eliminada_erp')

_BATCH = 500


def _aware(dt):
    """Datetime naive → aware en la zona por defecto. El parser (módulo puro, sin
    Django) produce datetimes naive; la BD (USE_TZ) los devuelve aware, así que se
    normalizan aquí antes de compararlos/guardarlos (Colombia no tiene DST)."""
    if dt is not None and timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_default_timezone())
    return dt


def _norm(texto):
    """lower + sin tildes (NFKD) + espacios colapsados. Para comparar categorías
    y estados ERP sin depender de tildes/mayúsculas ('EVALUACIÓN' → 'evaluacion')."""
    t = ' '.join(str(texto or '').split()).lower()
    return unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode()


def _es_formacion(categoria):
    """True si la categoría ERP es FORMACIÓN (no es material despachable)."""
    return _norm(categoria) == OrdenDespacho.CATEGORIA_FORMACION.lower()


def _es_anulada(vigencia):
    """True si la orden está anulada en el ERP ('Orden anulada')."""
    return 'anulada' in _norm(vigencia)


def _es_pendiente(estado_facturacion):
    """True si la facturación sigue 'Pendiente' (aún no hay remisión/factura)."""
    return _norm(estado_facturacion) == 'pendiente'


def _terminal_para(estado_facturacion):
    """Estado terminal de una orden anulada en el ERP: si su facturación ya es
    remisión/factura → REMITIDA (se despachó y facturó); si sigue 'Pendiente' →
    ANULADA (cancelada de verdad)."""
    norm = _norm(estado_facturacion)
    if norm.startswith('remision') or norm.startswith('factura'):
        return OrdenDespacho.Estado.REMITIDA
    return OrdenDespacho.Estado.ANULADA


def _cant_str(cantidad):
    """Decimal → texto compacto para el resumen: 17.00 → '17'; 17.50 → '17.5'."""
    c = Decimal(cantidad)
    if c == c.to_integral_value():
        return str(int(c))
    return format(c.normalize(), 'f')


def _denormalizar(incoming):
    """(es_despachable, n_lineas, resumen_articulos) desde las filas de la orden.
    Solo cuentan las líneas de material (categoría ≠ FORMACIÓN)."""
    material = [f for f in incoming if not _es_formacion(f.categoria)]
    partes = [f'{_cant_str(f.cantidad)}× {f.cod_articulo}' for f in material]
    resumen = '; '.join(partes)[:300]
    return bool(material), len(material), resumen


# ---------------------------------------------------------------------------
# Catálogo de artículos (upsert por código)
# ---------------------------------------------------------------------------

def _sync_catalogo(filas):
    """Upsert de `ArticuloERP` por código; devuelve {codigo: ArticuloERP} con pk.
    La primera aparición de cada código manda (descripciones consistentes)."""
    vistos = {}  # codigo -> (descripcion, categoria)
    for f in filas:
        if f.cod_articulo and f.cod_articulo not in vistos:
            vistos[f.cod_articulo] = (f.descripcion, f.categoria)

    catalogo = ArticuloERP.objects.in_bulk(list(vistos), field_name='codigo')
    crear, actualizar = [], []
    for cod, (desc, cat) in vistos.items():
        art = catalogo.get(cod)
        if art is None:
            art = ArticuloERP(codigo=cod, descripcion=desc, categoria=cat)
            crear.append(art)
            catalogo[cod] = art
        elif art.descripcion != desc or art.categoria != cat:
            art.descripcion, art.categoria = desc, cat
            actualizar.append(art)
    if crear:
        ArticuloERP.objects.bulk_create(crear, batch_size=_BATCH)
    if actualizar:
        ArticuloERP.objects.bulk_update(actualizar, ['descripcion', 'categoria'],
                                        batch_size=_BATCH)
    return catalogo


# ---------------------------------------------------------------------------
# Construcción / refresco de órdenes y líneas
# ---------------------------------------------------------------------------

def _nueva_orden(id_orden, incoming, ahora):
    """Instancia (sin guardar) una orden nueva desde su primera fila. Si NACE ya
    anulada (histórico del ERP) → estado terminal directo, SIN `cerrada_sin_marcar`
    ni eventos de alerta (no es un cierre 'sorpresa', es historia que llega tarde)."""
    prim = incoming[0]
    es_desp, n_lin, resumen = _denormalizar(incoming)
    orden = OrdenDespacho(
        id_orden=id_orden,
        es_despachable=es_desp, n_lineas=n_lin, resumen_articulos=resumen,
        **{c: getattr(prim, c) for c in _CAMPOS_ERP},
    )
    if _es_anulada(prim.vigencia):
        orden.estado = _terminal_para(prim.estado_facturacion)
        orden.cerrada_en = ahora
    return orden


def _snapshot(orden):
    """Tupla de los campos que el import puede tocar → detecta si algo cambió
    (para el contador de actualizadas e idempotencia)."""
    return tuple(getattr(orden, c) for c in _CAMPOS_UPDATE)


def _actualizar_orden(orden, incoming, eventos, ahora):
    """Refresca los datos ERP de una orden existente y aplica cierres/alertas.
    NO toca las marcas locales salvo las de estado que dicta el ERP."""
    prim = incoming[0]
    for c in _CAMPOS_ERP:
        setattr(orden, c, getattr(prim, c))
    orden.es_despachable, orden.n_lineas, orden.resumen_articulos = _denormalizar(incoming)

    estado_prev = orden.estado
    if estado_prev in OrdenDespacho.ESTADOS_TERMINALES:
        return  # ya cerrada: solo se refrescan datos ERP, sin nuevas transiciones

    if _es_anulada(prim.vigencia):
        # Cierre automático: el ERP cerró la orden (remisión → REMITIDA;
        # sigue Pendiente → ANULADA).
        orden.estado = _terminal_para(prim.estado_facturacion)
        orden.cerrada_en = ahora
        orden.alerta_remision = False
        if estado_prev == OrdenDespacho.Estado.DESPACHADA:
            eventos.append((orden, EventoOrden.Tipo.CIERRE_AUTO,
                            'Cerrada en el ERP tras el despacho marcado aquí.'))
        else:
            orden.cerrada_sin_marcar = True
            eventos.append((orden, EventoOrden.Tipo.CIERRE_SIN_MARCAR,
                            'Cerrada en el ERP sin que se marcara el despacho aquí.'))
    elif (estado_prev == OrdenDespacho.Estado.DESPACHADA
          and _es_pendiente(prim.estado_facturacion)):
        # Despachada aquí pero el ERP sigue vigente+pendiente: falta la remisión.
        if not orden.alerta_remision:
            orden.alerta_remision = True
            eventos.append((orden, EventoOrden.Tipo.ALERTA_REMISION,
                            'Despachada aquí; el ERP sigue vigente y pendiente '
                            '(falta generar la remisión).'))


def _nueva_linea(orden, fila, catalogo):
    return LineaOrden(
        orden=orden,
        articulo=catalogo.get(fila.cod_articulo),
        cod_articulo=fila.cod_articulo,
        descripcion=fila.descripcion,
        categoria=fila.categoria,
        cantidad=fila.cantidad,
        es_material=not _es_formacion(fila.categoria),
        orden_archivo=fila.orden_archivo,
    )


def _refrescar_linea(linea, fila, catalogo):
    """Actualiza los snapshots ERP de una línea existente. Devuelve True si algo
    cambió. Las marcas de cambio de material no se tocan (viven en la misma fila)."""
    art = catalogo.get(fila.cod_articulo)
    nuevos = {
        'articulo_id': art.pk if art else None,
        'cod_articulo': fila.cod_articulo,
        'descripcion': fila.descripcion,
        'categoria': fila.categoria,
        'cantidad': fila.cantidad,
        'es_material': not _es_formacion(fila.categoria),
        'orden_archivo': fila.orden_archivo,
    }
    cambio = False
    for campo, val in nuevos.items():
        if getattr(linea, campo) != val:
            setattr(linea, campo, val)
            cambio = True
    return cambio


def _sync_lineas(orden, incoming, existentes, catalogo, eventos):
    """Sincroniza las líneas de UNA orden conservando cambios de material.

    Matching por `cod_articulo` con ordinal para duplicados (n-ésima entrante con
    n-ésima existente, por `orden_archivo`). Sobrantes entrantes → crear;
    sobrantes existentes → borrar, SALVO con cambio de material marcado, que se
    conservan como rastro (`eliminada_erp=True` + evento LINEA_HUERFANA).

    Devuelve (crear, actualizar, borrar_pks, dirty)."""
    por_cod = defaultdict(deque)
    for l in existentes:
        por_cod[l.cod_articulo].append(l)

    crear, actualizar, borrar_pks = [], [], []
    dirty = False
    for fila in incoming:
        dq = por_cod.get(fila.cod_articulo)
        if dq:
            linea = dq.popleft()
            if _refrescar_linea(linea, fila, catalogo):
                actualizar.append(linea)
                dirty = True
        else:
            crear.append(_nueva_linea(orden, fila, catalogo))
            dirty = True

    for dq in por_cod.values():
        for linea in dq:  # existentes sin par entrante = el ERP las quitó
            if linea.articulo_cambio_id is not None:
                if not linea.eliminada_erp:  # idempotente: no re-emite el evento
                    linea.eliminada_erp = True
                    actualizar.append(linea)
                    eventos.append((orden, EventoOrden.Tipo.LINEA_HUERFANA,
                                    f'Línea {linea.cod_articulo} con cambio de '
                                    'material, eliminada en el ERP.'))
                    dirty = True
            else:
                borrar_pks.append(linea.pk)
                dirty = True
    return crear, actualizar, borrar_pks, dirty


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def importar_reporte(*, archivo, nombre_archivo, usuario):
    """Importa el reporte ERP y devuelve la `CargaReporte` creada.

    `archivo` = file-like binario (`request.FILES[...]`). Lanza `ReporteInvalido`
    (parser: faltan columnas) o `ReporteViejo` (anti-archivo-viejo)."""
    parsed = parsear_reporte(archivo)  # FUERA de la transacción; puede lanzar ReporteInvalido

    # Normalizar los datetimes naive del parser a aware (evita comparar naive vs
    # aware contra los valores que la BD devuelve aware, y guarda sin warnings).
    parsed.max_fecha_orden = _aware(parsed.max_fecha_orden)
    for fila in parsed.filas:
        fila.fecha_orden = _aware(fila.fecha_orden)

    ultima = CargaReporte.objects.order_by('-creado_en').first()
    if (ultima and ultima.max_fecha_orden and parsed.max_fecha_orden
            and parsed.max_fecha_orden < ultima.max_fecha_orden):
        raise ReporteViejo(
            f'El archivo es más antiguo que la última carga '
            f'({parsed.max_fecha_orden:%Y-%m-%d %H:%M} < '
            f'{ultima.max_fecha_orden:%Y-%m-%d %H:%M}). ¿Subiste un reporte viejo?')

    with transaction.atomic():
        return _aplicar(parsed, nombre_archivo, usuario)


def _aplicar(parsed, nombre_archivo, usuario):
    ahora = timezone.now()
    filas = parsed.filas

    # 1. Agrupar filas por orden (preservando el orden de aparición en el archivo).
    grupos = {}
    for fila in filas:
        grupos.setdefault(fila.id_orden, []).append(fila)

    # 2. Catálogo de artículos.
    catalogo = _sync_catalogo(filas)

    # 3. Órdenes ya conocidas + sus líneas (una sola query cada uno).
    existentes = OrdenDespacho.objects.in_bulk(list(grupos), field_name='id_orden')
    lineas_por_orden = defaultdict(list)
    if existentes:
        qs = (LineaOrden.objects
              .filter(orden_id__in=[o.pk for o in existentes.values()])
              .order_by('orden_archivo', 'id'))
        for l in qs:
            lineas_por_orden[l.orden_id].append(l)

    # 4. La carga se crea ya (los eventos la referencian); los contadores se
    #    completan al final.
    carga = CargaReporte.objects.create(
        usuario=usuario, nombre_archivo=nombre_archivo,
        max_fecha_orden=parsed.max_fecha_orden,
        n_filas=len(filas), n_ordenes=len(grupos),
        n_descartadas=parsed.n_descartadas)

    ordenes_nuevas = []       # (orden, incoming) — sus líneas se crean tras el bulk_create
    ordenes_actualizar = []
    lineas_crear, lineas_actualizar, lineas_borrar = [], [], []
    eventos = []              # (orden_obj, tipo, detalle) — todos automáticos (sin usuario)
    n_nuevas = n_actualizadas = 0

    for id_orden, incoming in grupos.items():
        orden = existentes.get(id_orden)
        if orden is None:
            ordenes_nuevas.append((_nueva_orden(id_orden, incoming, ahora), incoming))
            n_nuevas += 1
            continue
        antes = _snapshot(orden)
        _actualizar_orden(orden, incoming, eventos, ahora)
        c, u, b, dirty_lineas = _sync_lineas(
            orden, incoming, lineas_por_orden.get(orden.pk, []), catalogo, eventos)
        lineas_crear += c
        lineas_actualizar += u
        lineas_borrar += b
        if _snapshot(orden) != antes or dirty_lineas:
            ordenes_actualizar.append(orden)
            n_actualizadas += 1

    # 5. Persistir en bloque. Las nuevas primero (para que tengan pk antes de
    #    crear sus líneas y sus eventos).
    if ordenes_nuevas:
        OrdenDespacho.objects.bulk_create([o for o, _ in ordenes_nuevas], batch_size=_BATCH)
        for orden, incoming in ordenes_nuevas:
            for fila in incoming:
                lineas_crear.append(_nueva_linea(orden, fila, catalogo))
    if ordenes_actualizar:
        OrdenDespacho.objects.bulk_update(ordenes_actualizar, list(_CAMPOS_UPDATE),
                                          batch_size=_BATCH)
    if lineas_crear:
        LineaOrden.objects.bulk_create(lineas_crear, batch_size=_BATCH)
    if lineas_actualizar:
        LineaOrden.objects.bulk_update(lineas_actualizar, list(_CAMPOS_LINEA_UPDATE),
                                       batch_size=_BATCH)
    if lineas_borrar:
        LineaOrden.objects.filter(pk__in=lineas_borrar).delete()
    if eventos:
        EventoOrden.objects.bulk_create(
            [EventoOrden(orden=orden, tipo=tipo, detalle=detalle,
                         usuario=None, carga=carga)
             for orden, tipo, detalle in eventos], batch_size=_BATCH)

    # 6. Contadores derivados de los eventos.
    cierres = (EventoOrden.Tipo.CIERRE_AUTO, EventoOrden.Tipo.CIERRE_SIN_MARCAR)
    carga.n_nuevas = n_nuevas
    carga.n_actualizadas = n_actualizadas
    carga.n_cerradas_auto = sum(1 for _, t, _ in eventos if t in cierres)
    carga.n_alertas_remision = sum(
        1 for _, t, _ in eventos if t == EventoOrden.Tipo.ALERTA_REMISION)
    carga.save(update_fields=['n_nuevas', 'n_actualizadas', 'n_cerradas_auto',
                              'n_alertas_remision'])
    return carga


# ---------------------------------------------------------------------------
# Acciones locales (F4): estado de trabajo + cambio de material
#
# Únicas puertas de escritura de las marcas locales. Cada acción es
# `transaction.atomic` y deja un `EventoOrden` (bitácora append-only). Los
# estados terminales (REMITIDA/ANULADA) los fija SOLO el import; estas acciones
# nunca los tocan.
# ---------------------------------------------------------------------------

# Acciones de estado admitidas (body `accion` de la vista).
ALISTAR, DESPACHAR, REVERTIR = 'alistar', 'despachar', 'revertir'
ACCIONES_ESTADO = (ALISTAR, DESPACHAR, REVERTIR)


def _evento(orden, tipo, detalle, usuario, carga=None):
    """Crea un `EventoOrden` (append-only). `usuario=None` = evento automático."""
    return EventoOrden.objects.create(orden=orden, tipo=tipo, detalle=detalle,
                                      usuario=usuario, carga=carga)


@transaction.atomic
def marcar_estado(*, orden, accion, usuario):
    """Aplica una transición de estado local a una orden y registra el evento.

    Flujo estricto PENDIENTE → ALISTADA → DESPACHADA; `revertir` retrocede
    exactamente un paso. Los estados terminales (REMITIDA/ANULADA, fijados por el
    import) rechazan toda acción. Fija/limpia el par usuario/fecha del paso.
    Lanza `TransicionInvalida` si la acción no aplica al estado actual."""
    Estado = OrdenDespacho.Estado
    estado = orden.estado
    ahora = timezone.now()

    if estado in OrdenDespacho.ESTADOS_TERMINALES:
        raise TransicionInvalida(
            f'La orden {orden.id_orden} está cerrada en el ERP '
            f'({orden.get_estado_display()}); no admite cambios de estado.')

    if accion == ALISTAR:
        if estado != Estado.PENDIENTE:
            raise TransicionInvalida('Solo se puede alistar una orden pendiente.')
        orden.estado = Estado.ALISTADA
        orden.alistada_por, orden.alistada_en = usuario, ahora
        _evento(orden, EventoOrden.Tipo.ALISTADA, 'Orden alistada.', usuario)

    elif accion == DESPACHAR:
        if estado != Estado.ALISTADA:
            raise TransicionInvalida('Solo se puede despachar una orden alistada.')
        orden.estado = Estado.DESPACHADA
        orden.despachada_por, orden.despachada_en = usuario, ahora
        _evento(orden, EventoOrden.Tipo.DESPACHADA, 'Orden despachada.', usuario)

    elif accion == REVERTIR:
        if estado == Estado.DESPACHADA:
            orden.estado = Estado.ALISTADA
            orden.despachada_por = orden.despachada_en = None
            orden.alerta_remision = False  # ya no está despachada → sin alerta
            _evento(orden, EventoOrden.Tipo.REVERTIDA,
                    'Despacho revertido (vuelve a Alistada).', usuario)
        elif estado == Estado.ALISTADA:
            orden.estado = Estado.PENDIENTE
            orden.alistada_por = orden.alistada_en = None
            _evento(orden, EventoOrden.Tipo.REVERTIDA,
                    'Alistamiento revertido (vuelve a Pendiente).', usuario)
        else:
            raise TransicionInvalida(
                'La orden ya está pendiente; no hay nada que revertir.')
    else:
        raise TransicionInvalida(f'Acción de estado desconocida: {accion!r}.')

    orden.save()
    return orden


@transaction.atomic
def registrar_cambio_material(*, linea, articulo_destino, cantidad, usuario):
    """Marca un cambio de material en una línea: se despachará `articulo_destino`
    (cantidad `cantidad`) en vez del artículo original. Deja la línea con
    `pendiente_erp=True` (falta reflejarlo en el ERP) y registra el evento.
    Rechaza órdenes cerradas en el ERP (`TransicionInvalida`) y cantidades no
    positivas (`ValueError`). `cantidad` puede venir como str/Decimal."""
    if linea.orden.terminal:
        raise TransicionInvalida('No se puede cambiar el material de una orden '
                                 'cerrada en el ERP.')
    cantidad = Decimal(cantidad)  # InvalidOperation si el texto no es numérico
    if cantidad <= 0:
        raise ValueError('La cantidad del cambio debe ser mayor que cero.')

    linea.articulo_cambio = articulo_destino
    linea.cantidad_cambio = cantidad
    linea.cambiado_por = usuario
    linea.cambiado_en = timezone.now()
    linea.pendiente_erp = True
    linea.save(update_fields=['articulo_cambio', 'cantidad_cambio',
                              'cambiado_por', 'cambiado_en', 'pendiente_erp'])
    _evento(linea.orden, EventoOrden.Tipo.CAMBIO_MATERIAL,
            f'{linea.cod_articulo} → {articulo_destino.codigo} '
            f'({_cant_str(cantidad)}).', usuario)
    return linea


@transaction.atomic
def revertir_cambio_material(*, linea, usuario):
    """Quita el cambio de material de una línea (vuelve al artículo original) y
    registra el evento. Lanza `TransicionInvalida` si la línea no tenía cambio."""
    if linea.articulo_cambio_id is None:
        raise TransicionInvalida('Esta línea no tiene un cambio de material.')
    detalle = f'{linea.cod_articulo} → {linea.articulo_cambio.codigo}: revertido.'
    linea.articulo_cambio = None
    linea.cantidad_cambio = None
    linea.cambiado_por = None
    linea.cambiado_en = None
    linea.pendiente_erp = False
    linea.save(update_fields=['articulo_cambio', 'cantidad_cambio',
                              'cambiado_por', 'cambiado_en', 'pendiente_erp'])
    _evento(linea.orden, EventoOrden.Tipo.CAMBIO_REVERTIDO, detalle, usuario)
    return linea


@transaction.atomic
def marcar_erp_actualizado(*, linea, usuario, hecho):
    """Marca (`hecho=True`) o vuelve a marcar pendiente (`hecho=False`) que el
    cambio de material ya se reflejó en el ERP. Solo aplica a líneas con cambio
    (`TransicionInvalida` si no lo tienen)."""
    if linea.articulo_cambio_id is None:
        raise TransicionInvalida('Esta línea no tiene un cambio de material.')
    linea.pendiente_erp = not hecho
    linea.save(update_fields=['pendiente_erp'])
    detalle = ('Cambio de material reflejado en el ERP.' if hecho
               else 'Cambio de material marcado de nuevo como pendiente en el ERP.')
    _evento(linea.orden, EventoOrden.Tipo.ERP_ACTUALIZADO, detalle, usuario)
    return linea
