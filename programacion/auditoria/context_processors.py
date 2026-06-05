from django.core.cache import cache


def alertas_vigentes(request):
    # request.user puede no existir si el error se dispara antes de
    # AuthenticationMiddleware (p. ej. el 404 de un subdominio sin área, que lanza
    # EnrutadoPorAreaMiddleware antes que la auth) → la página de error igual renderiza.
    user = getattr(request, 'user', None)
    # El módulo de auditoría es accesible a todo el personal de programación
    # (superusuario o staff de área), igual que la vista lista_alertas — no solo al
    # superusuario. Se usa el flag que fija el middleware para no recalcular el grupo.
    if not (user and user.is_authenticated and getattr(request, 'es_personal_programacion', False)):
        return {}
    count = cache.get('alertas_vigentes_count')
    if count is None:
        from programacion.auditoria.models import AlertaAuditoria
        count = AlertaAuditoria.objects.filter(vigente=True).count()
        cache.set('alertas_vigentes_count', count, 60)
    return {'alertas_vigentes_count': count}
