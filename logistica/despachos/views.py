"""Vistas de despachos.

F2: carga del reporte diario. F3: tablero (3 tabs) + detalle de orden. F4:
acciones de estado (alistar/despachar/revertir) y cambio de material por línea.
F5: badge (context processor), export a Excel del tablero con filtros vigentes,
bodega por defecto por usuario y su gestión (superusuario). Gate `@solo_logistica`
(el middleware ya bloquea el subdominio; el decorador es la segunda barrera).
Todas las acciones son POST-redirect con feedback por `messages` (logística sí
muestra toasts).
"""
from datetime import datetime, timedelta
from decimal import InvalidOperation

from django.contrib import messages
from django.contrib.auth.models import Group, User
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.areas import GRUPO_STAFF_LOGISTICA
# Los helpers de Excel se reutilizan tal cual del inventario (mismo trade-off
# self-contained openpyxl); no se duplica la maquinaria de la hoja.
from logistica.inventario.views import _generar_excel, _respuesta_xlsx

from .forms import CargaReporteForm
from .models import (ArticuloERP, AsignacionBodega, CargaReporte, LineaOrden,
                     OrdenDespacho)
from .permisos import solo_logistica
from .reporte import ReporteInvalido
from .services import (ReporteViejo, TransicionInvalida, importar_reporte,
                       marcar_erp_actualizado, marcar_estado,
                       registrar_cambio_material, revertir_cambio_material)

# Filtros de columna del tablero (name en el POST del export → campo del modelo).
# `f_cliente` (columna "Colegio") NO está aquí: se filtra sobre `centro_costos` con
# fallback a `cliente`, que no es un simple `icontains` (ver `tablero_exportar`).
FILTROS_COLUMNA = {
    'f_orden': 'id_orden', 'f_bodega': 'bodega',
    'f_ciudad': 'ciudad', 'f_depto': 'departamento', 'f_articulo': 'resumen_articulos',
}

# Tabs del tablero (querystring `?tab=`).
TABS = ('abiertas', 'sin_remision', 'cerradas')
# La tab "Cerradas" crece sin tope (todo el histórico) → se sirve por rango sobre
# `fecha_orden`; el resto del histórico sale por el export (F5).
DIAS_CERRADAS = 30
DIAS_PROXIMA = 7  # ventana de "próxima a vencer" (resaltado amarillo)


def _parse_fecha(valor):
    """'YYYY-MM-DD' → date, o None si está vacío/mal formado (no revienta)."""
    try:
        return datetime.strptime((valor or '').strip(), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _normaliza_tab(valor):
    return valor if valor in TABS else 'abiertas'


def _queryset_tab(tab, *, desde=None, hasta=None):
    """Queryset base de cada tab (misma lógica que comparten tablero y export).
    `desde`/`hasta` solo aplican a la tab "cerradas" (rango de `fecha_orden`)."""
    if tab == 'abiertas':
        return OrdenDespacho.objects.filter(
            estado__in=OrdenDespacho.ESTADOS_ABIERTOS, es_despachable=True)
    if tab == 'sin_remision':
        return OrdenDespacho.objects.filter(estado=OrdenDespacho.Estado.DESPACHADA)
    qs = OrdenDespacho.objects.filter(estado__in=OrdenDespacho.ESTADOS_TERMINALES)
    if desde:
        qs = qs.filter(fecha_orden__date__gte=desde)
    if hasta:
        qs = qs.filter(fecha_orden__date__lte=hasta)
    return qs


@solo_logistica
def tablero(request):
    """Tablero de órdenes con 3 tabs (por despachar / despachadas sin remisión /
    cerradas). Filtros por columna y atajos de fecha son client-side (patrón
    viáticos); la tab "cerradas" acota por rango de `fecha_orden` en el server.

    `?q=PPAL-N` es un salto rápido al detalle de una orden (cualquier estado)."""
    hoy = timezone.localdate()

    # Salto rápido por número de orden (tolerante al prefijo PPAL-).
    q = (request.GET.get('q') or '').strip()
    if q:
        orden = OrdenDespacho.objects.filter(id_orden__iexact=q).first()
        if orden is None and not q.upper().startswith('PPAL-'):
            orden = OrdenDespacho.objects.filter(id_orden__iexact=f'PPAL-{q}').first()
        if orden is not None:
            return redirect('log_despachos_detalle', pk=orden.pk)
        messages.warning(request, f'No se encontró ninguna orden «{q}».')

    tab = _normaliza_tab(request.GET.get('tab'))

    # Contadores de las tabs de trabajo (cheap COUNTs, cubiertos por el índice).
    n_abiertas = OrdenDespacho.objects.filter(
        estado__in=OrdenDespacho.ESTADOS_ABIERTOS, es_despachable=True).count()
    n_sin_remision = OrdenDespacho.objects.filter(
        estado=OrdenDespacho.Estado.DESPACHADA).count()

    # Rango de la tab "cerradas" (solo se usa ahí; default últimos 30 días).
    desde = _parse_fecha(request.GET.get('desde')) or (hoy - timedelta(days=DIAS_CERRADAS))
    hasta = _parse_fecha(request.GET.get('hasta')) or hoy

    ordenes = _queryset_tab(tab, desde=desde, hasta=hasta)

    # Bodega por defecto del usuario (pre-puebla el filtro de bodega, borrable).
    asignacion = AsignacionBodega.objects.filter(usuario=request.user).first()

    return render(request, 'despachos/tablero.html', {
        'tab': tab,
        'ordenes': ordenes,
        'n_abiertas': n_abiertas,
        'n_sin_remision': n_sin_remision,
        'hoy': hoy,
        'limite_proxima': hoy + timedelta(days=DIAS_PROXIMA),
        'desde': desde,
        'hasta': hasta,
        'q': q,
        'bodega_default': asignacion.bodega if asignacion else '',
    })


@solo_logistica
def orden_detalle(request, pk):
    """Detalle de una orden: datos ERP, líneas de material (FORMACIÓN colapsada
    aparte) e historial de eventos append-only."""
    orden = get_object_or_404(
        OrdenDespacho.objects.prefetch_related(
            'lineas__articulo', 'lineas__articulo_cambio'),
        pk=pk)
    lineas = list(orden.lineas.all())
    # Catálogo para el modal de cambio de material (select2). Solo hace falta si
    # la orden aún admite cambios (no terminal); el select se puebla una vez.
    articulos = () if orden.terminal else ArticuloERP.objects.all()
    return render(request, 'despachos/orden_detalle.html', {
        'orden': orden,
        'lineas_material': [l for l in lineas if l.es_material],
        'lineas_formacion': [l for l in lineas if not l.es_material],
        'eventos': orden.eventos.select_related('usuario', 'carga')[:100],
        'articulos': articulos,
        'hoy': timezone.localdate(),
    })


# ---------------------------------------------------------------------------
# Acciones (F4) — POST-redirect, gate COMPLETO (LECTURA las bloquea en el
# middleware). Los errores de dominio se traducen a `messages.error`.
# ---------------------------------------------------------------------------

def _volver(request, orden):
    """Redirige al `next` del POST si es una URL local segura; si no, al detalle.
    Permite que las acciones desde el tablero regresen a la misma tab/filtro."""
    destino = request.POST.get('next') or ''
    if destino and url_has_allowed_host_and_scheme(
            destino, allowed_hosts={request.get_host()},
            require_https=request.is_secure()):
        return redirect(destino)
    return redirect('log_despachos_detalle', pk=orden.pk)


@require_POST
@solo_logistica
def orden_estado(request, pk):
    """Transición de estado local (body `accion` ∈ alistar/despachar/revertir)."""
    orden = get_object_or_404(OrdenDespacho, pk=pk)
    accion = (request.POST.get('accion') or '').strip()
    try:
        marcar_estado(orden=orden, accion=accion, usuario=request.user)
        messages.success(
            request, f'Orden {orden.id_orden}: {orden.get_estado_display().lower()}.')
    except TransicionInvalida as exc:
        messages.error(request, str(exc))
    return _volver(request, orden)


@require_POST
@solo_logistica
def linea_cambio(request, pk):
    """Registra un cambio de material en una línea (artículo destino + cantidad)."""
    linea = get_object_or_404(LineaOrden.objects.select_related('orden'), pk=pk)
    articulo_id = request.POST.get('articulo_id', '')
    if not articulo_id.isdigit():
        messages.error(request, 'Selecciona el artículo de reemplazo.')
        return redirect('log_despachos_detalle', pk=linea.orden_id)
    articulo = get_object_or_404(ArticuloERP, pk=articulo_id)
    cantidad = (request.POST.get('cantidad') or '').replace(',', '.').strip()
    try:
        registrar_cambio_material(linea=linea, articulo_destino=articulo,
                                  cantidad=cantidad, usuario=request.user)
        messages.success(
            request, f'Cambio de material registrado en {linea.cod_articulo}.')
    except (TransicionInvalida, ValueError, InvalidOperation) as exc:
        messages.error(request, str(exc) or 'La cantidad del cambio es inválida.')
    return redirect('log_despachos_detalle', pk=linea.orden_id)


@require_POST
@solo_logistica
def linea_cambio_quitar(request, pk):
    """Quita el cambio de material de una línea (vuelve al artículo original)."""
    linea = get_object_or_404(
        LineaOrden.objects.select_related('orden', 'articulo_cambio'), pk=pk)
    try:
        revertir_cambio_material(linea=linea, usuario=request.user)
        messages.success(
            request, f'Cambio de material de {linea.cod_articulo} revertido.')
    except TransicionInvalida as exc:
        messages.error(request, str(exc))
    return redirect('log_despachos_detalle', pk=linea.orden_id)


@require_POST
@solo_logistica
def linea_erp_toggle(request, pk):
    """Marca/desmarca que el cambio de material ya se reflejó en el ERP
    (body `hecho=1` → reflejado; cualquier otro valor → pendiente de nuevo)."""
    linea = get_object_or_404(LineaOrden.objects.select_related('orden'), pk=pk)
    hecho = request.POST.get('hecho') == '1'
    try:
        marcar_erp_actualizado(linea=linea, usuario=request.user, hecho=hecho)
        messages.success(request, 'Estado del cambio en el ERP actualizado.')
    except TransicionInvalida as exc:
        messages.error(request, str(exc))
    return redirect('log_despachos_detalle', pk=linea.orden_id)


@solo_logistica
def cargar(request):
    """GET: form de subida + historial de cargas (bitácora + 'datos al día de…').
    POST: parsea e importa el reporte; traduce los errores de dominio a toasts."""
    if request.method == 'POST':
        form = CargaReporteForm(request.POST, request.FILES)
        if not form.is_valid():
            for errores in form.errors.values():
                for error in errores:
                    messages.error(request, error)
            return redirect('log_despachos_cargar')

        archivo = form.cleaned_data['archivo']
        try:
            carga = importar_reporte(archivo=archivo, nombre_archivo=archivo.name,
                                     usuario=request.user)
        except (ReporteInvalido, ReporteViejo) as exc:
            messages.error(request, str(exc))
            return redirect('log_despachos_cargar')

        messages.success(
            request,
            f'Reporte importado: {carga.n_ordenes} órdenes '
            f'({carga.n_nuevas} nuevas, {carga.n_actualizadas} actualizadas, '
            f'{carga.n_cerradas_auto} cerradas, {carga.n_alertas_remision} alertas).')
        return redirect('log_despachos_cargar')

    cargas = CargaReporte.objects.select_related('usuario')[:30]
    return render(request, 'despachos/cargar.html', {
        'form': CargaReporteForm(),
        'cargas': cargas,
        'ultima': cargas[0] if cargas else None,
    })


# ---------------------------------------------------------------------------
# Export a Excel (F5) — POST desde el modal del tablero; el JS copia los filtros
# vigentes (tab + columnas + rango de fecha) a inputs hidden y el server los
# re-aplica al queryset (patrón `fin_viaticos_exportar`). Permitido en LECTURA
# (ruta `/despachos/exportar/` declarada en `posts_lectura` de `core/modulos.py`).
# ---------------------------------------------------------------------------

@require_POST
@solo_logistica
def tablero_exportar(request):
    """Exporta el tablero (la tab y filtros vigentes) a Excel. Sin cap: se
    exporta todo lo que casa los filtros, no la página."""
    tab = _normaliza_tab(request.POST.get('tab'))
    desde = _parse_fecha(request.POST.get('desde'))
    hasta = _parse_fecha(request.POST.get('hasta'))
    ordenes = _queryset_tab(tab, desde=desde, hasta=hasta)

    # Filtros por columna (icontains, como el client-side del tablero).
    for campo_post, campo_modelo in FILTROS_COLUMNA.items():
        valor = (request.POST.get(campo_post) or '').strip()
        if valor:
            ordenes = ordenes.filter(**{f'{campo_modelo}__icontains': valor})

    # Columna "Colegio" = centro_costos con fallback a cliente: el filtro casa
    # sobre centro_costos o, si viene vacío, sobre cliente (espeja `OrdenDespacho.colegio`).
    colegio = (request.POST.get('f_cliente') or '').strip()
    if colegio:
        ordenes = ordenes.filter(
            Q(centro_costos__icontains=colegio)
            | Q(centro_costos='', cliente__icontains=colegio))

    # Rango de fecha de entrega (atajos/rango client-side de las tabs de trabajo).
    ent_desde = _parse_fecha(request.POST.get('ent_desde'))
    ent_hasta = _parse_fecha(request.POST.get('ent_hasta'))
    if ent_desde:
        ordenes = ordenes.filter(fecha_entrega__gte=ent_desde)
    if ent_hasta:
        ordenes = ordenes.filter(fecha_entrega__lte=ent_hasta)

    filas = []
    for o in ordenes:
        alertas = []
        if o.alerta_remision:
            alertas.append('Falta remisión')
        if o.cerrada_sin_marcar:
            alertas.append('Cerrada sin marcar')
        filas.append([
            o.id_orden, o.colegio, o.bodega, o.ciudad, o.departamento,
            o.direccion, o.telefono, o.vendedor, o.resumen_articulos, o.n_lineas,
            o.fecha_entrega.strftime('%Y-%m-%d') if o.fecha_entrega else '',
            o.fecha_orden.strftime('%Y-%m-%d %H:%M') if o.fecha_orden else '',
            o.get_estado_display(), o.estado_facturacion, o.vigencia,
            '; '.join(alertas),
        ])
    excel = _generar_excel(
        titulo='Despachos',
        columnas=['N° orden', 'Colegio', 'Bodega', 'Ciudad', 'Departamento',
                  'Dirección', 'Teléfono', 'Vendedor', 'Artículos', 'N° líneas',
                  'Fecha entrega', 'Fecha orden', 'Estado', 'Facturación ERP',
                  'Vigencia', 'Alertas'],
        filas=filas,
        anchos=[12, 28, 14, 14, 16, 30, 14, 20, 30, 9, 13, 17, 12, 24, 14, 22])
    hoy = timezone.localdate().strftime('%Y%m%d')
    return _respuesta_xlsx(excel, f'Despachos_{tab}_{hoy}.xlsx')


# ---------------------------------------------------------------------------
# Bodega por usuario (F5) — asignación formal user→bodega que fija el filtro por
# defecto del tablero. La gestiona SOLO el superusuario (patrón
# `plantilla_eliminar`: el template oculta la página y la vista rechaza el POST).
# ---------------------------------------------------------------------------

def _bodegas_erp():
    """Bodegas distintas vistas en el ERP (para el select de asignación)."""
    return list(OrdenDespacho.objects
                .exclude(bodega='')
                .values_list('bodega', flat=True)
                .distinct().order_by('bodega'))


@solo_logistica
def bodegas_usuarios(request):
    """Página de gestión de la bodega por defecto de cada usuario de logística.
    Solo superusuario: el ítem no aparece a otros roles y el POST se rechaza."""
    if not request.user.is_superuser:
        messages.error(request, 'Solo el administrador puede gestionar bodegas.')
        return redirect('log_despachos_tablero')

    if request.method == 'POST':
        usuario = get_object_or_404(User, pk=request.POST.get('user_id', ''))
        bodega = (request.POST.get('bodega') or '').strip()
        if bodega:
            AsignacionBodega.objects.update_or_create(
                usuario=usuario,
                defaults={'bodega': bodega, 'asignado_por': request.user})
            messages.success(
                request, f'Bodega de {usuario.username}: {bodega}.')
        else:
            AsignacionBodega.objects.filter(usuario=usuario).delete()
            messages.success(
                request, f'{usuario.username} ya no tiene bodega por defecto.')
        return redirect('log_despachos_bodegas')

    # Usuarios del área (grupo de etiqueta) + los que ya tengan asignación.
    grupo = Group.objects.filter(name=GRUPO_STAFF_LOGISTICA).first()
    usuarios = User.objects.filter(is_active=True)
    if grupo:
        usuarios = usuarios.filter(groups=grupo)
    else:
        usuarios = usuarios.filter(bodega_despachos__isnull=False)
    usuarios = (usuarios.exclude(is_superuser=True)
                .select_related('bodega_despachos')
                .order_by('username').distinct())

    return render(request, 'despachos/bodegas.html', {
        'usuarios': usuarios,
        'bodegas': _bodegas_erp(),
    })
