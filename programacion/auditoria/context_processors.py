from django.core.cache import cache


def alertas_vigentes(request):
    # request.user puede no existir si el error se dispara antes de
    # AuthenticationMiddleware (p. ej. el 404 de un subdominio sin área, que lanza
    # EnrutadoPorAreaMiddleware antes que la auth) → la página de error igual renderiza.
    user = getattr(request, 'user', None)
    if not (user and user.is_authenticated and user.is_superuser):
        return {}
    count = cache.get('alertas_vigentes_count')
    if count is None:
        from programacion.auditoria.models import AlertaAuditoria
        count = AlertaAuditoria.objects.filter(vigente=True).count()
        cache.set('alertas_vigentes_count', count, 60)
    return {'alertas_vigentes_count': count}
