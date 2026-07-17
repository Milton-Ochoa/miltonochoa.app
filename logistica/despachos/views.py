"""Vistas de despachos.

F2: carga del reporte diario. F3: tablero (3 tabs) + detalle de orden. Las
acciones de estado/cambio de material llegan en F4; el badge/export/bodega por
defecto en F5. Gate `@solo_logistica` (el middleware ya bloquea el subdominio; el
decorador es la segunda barrera). La carga es un POST-redirect con feedback por
`messages` (logística sí muestra toasts).
"""
from datetime import datetime, timedelta

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import CargaReporteForm
from .models import CargaReporte, OrdenDespacho
from .permisos import solo_logistica
from .reporte import ReporteInvalido
from .services import ReporteViejo, importar_reporte

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
    return render(request, 'despachos/orden_detalle.html', {
        'orden': orden,
        'lineas_material': [l for l in lineas if l.es_material],
        'lineas_formacion': [l for l in lineas if not l.es_material],
        'eventos': orden.eventos.select_related('usuario', 'carga')[:100],
        'hoy': timezone.localdate(),
    })


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
