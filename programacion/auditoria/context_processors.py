from django.core.cache import cache


def alertas_vigentes(request):
    if not (request.user.is_authenticated and request.user.is_superuser):
        return {}
    count = cache.get('alertas_vigentes_count')
    if count is None:
        from auditoria.models import AlertaAuditoria
        count = AlertaAuditoria.objects.filter(vigente=True).count()
        cache.set('alertas_vigentes_count', count, 60)
    return {'alertas_vigentes_count': count}
