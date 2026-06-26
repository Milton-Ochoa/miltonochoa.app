"""Context processors de los badges del menú de programación (área monitores):
**Simulacros** (próximos sin monitor) y **Pagos → Monitores** (por enviar)."""


def simulacros_sin_monitor(request):
    """Contador para el badge del ítem **Simulacros** (Operaciones): simulacros en
    los próximos 7 días sin ningún monitor asignado.

    Solo se calcula en el subdominio programación y para su personal
    (`request.es_personal_programacion`, que fija usuarios.middleware) → en el apex
    y en las otras áreas no corre la query. Es un COUNT directo (barato).
    """
    if getattr(request, 'area', None) != 'programacion':
        return {}
    if not getattr(request, 'es_personal_programacion', False):
        return {}
    from .avisos import simulacros_proximos_sin_monitor
    return {'simulacros_sin_monitor_count': simulacros_proximos_sin_monitor().count()}


def pagos_monitores_por_revisar(request):
    """Contador para el badge del ítem **Pagos → Monitores** (Reportes): filas
    **pendientes por enviar** a financiera (lote BORRADOR, no excluidas), de todas las
    semanas (backlog completo). Espejo de ``programacion.pagos.context_processors``.

    Solo se calcula en el subdominio programación y para su personal. COUNT directo.
    """
    if getattr(request, 'area', None) != 'programacion':
        return {}
    if not getattr(request, 'es_personal_programacion', False):
        return {}
    from .models import LoteMonitores, PagoMonitor
    n = (PagoMonitor.objects
         .filter(lote__estado=LoteMonitores.Estado.BORRADOR, excluida=False)
         .count())
    return {'pagos_monitores_por_revisar_count': n}
