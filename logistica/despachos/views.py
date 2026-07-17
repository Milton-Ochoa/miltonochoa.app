"""Vistas de despachos.

F2: carga del reporte diario. F3: tablero (3 tabs) + detalle de orden. F4:
acciones de estado (alistar/despachar/revertir) y cambio de material por línea.
El badge/export/bodega por defecto llegan en F5. Gate `@solo_logistica` (el
middleware ya bloquea el subdominio; el decorador es la segunda barrera). Todas
las acciones son POST-redirect con feedback por `messages` (logística sí muestra
toasts).
"""
from datetime import datetime, timedelta
from decimal import InvalidOperation

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import CargaReporteForm
from .models import ArticuloERP, CargaReporte, LineaOrden, OrdenDespacho
from .permisos import solo_logistica
from .reporte import ReporteInvalido
from .services import (ReporteViejo, TransicionInvalida, importar_reporte,
                       marcar_erp_actualizado, marcar_estado,
                       registrar_cambio_material, revertir_cambio_material)

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

    tab = request.GET.get('tab')
    if tab not in TABS:
        tab = 'abiertas'

    # Contadores de las tabs de trabajo (cheap COUNTs, cubiertos por el índice).
    n_abiertas = OrdenDespacho.objects.filter(
        estado__in=OrdenDespacho.ESTADOS_ABIERTOS, es_despachable=True).count()
    n_sin_remision = OrdenDespacho.objects.filter(
        estado=OrdenDespacho.Estado.DESPACHADA).count()

    # Rango de la tab "cerradas" (solo se usa ahí; default últimos 30 días).
    desde = _parse_fecha(request.GET.get('desde')) or (hoy - timedelta(days=DIAS_CERRADAS))
    hasta = _parse_fecha(request.GET.get('hasta')) or hoy

    if tab == 'abiertas':
        ordenes = OrdenDespacho.objects.filter(
            estado__in=OrdenDespacho.ESTADOS_ABIERTOS, es_despachable=True)
    elif tab == 'sin_remision':
        ordenes = OrdenDespacho.objects.filter(estado=OrdenDespacho.Estado.DESPACHADA)
    else:  # cerradas
        ordenes = OrdenDespacho.objects.filter(
            estado__in=OrdenDespacho.ESTADOS_TERMINALES,
            fecha_orden__date__gte=desde, fecha_orden__date__lte=hasta)

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
