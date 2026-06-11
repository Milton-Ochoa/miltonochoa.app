def viaticos_pendientes(request):
    """Contador de solicitudes pendientes de gestión por financiera (`ENVIADA` +
    `LEG_ENVIADA`) para el badge del menú.

    Solo se calcula en peticiones del subdominio financiera y para su personal
    (`request.es_personal_financiera`, que fija usuarios.middleware) → en el apex y
    en programación no corre la query ni ensucia el contexto. Sin cache: la cuenta es
    barata y el badge debe reflejar al instante lo que financiera devuelve/aprueba.
    """
    if getattr(request, 'area', None) != 'financiera':
        return {}
    if not getattr(request, 'es_personal_financiera', False):
        return {}
    from programacion.viaticos.models import SolicitudViatico
    count = SolicitudViatico.objects.filter(estado__in=[
        SolicitudViatico.Estado.ENVIADA,
        SolicitudViatico.Estado.LEG_ENVIADA,
    ]).count()
    return {'viaticos_pendientes_count': count}
