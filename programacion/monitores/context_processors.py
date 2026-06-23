"""Context processor del badge de **Simulacros** en el menú de programación."""


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
