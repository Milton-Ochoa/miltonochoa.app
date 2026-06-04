def pagos_por_revisar(request):
    """Contador para el badge del menú **Pagos** en programación: todas las filas
    **pendientes por enviar** a financiera (lote BORRADOR, no excluidas), de todas las
    semanas (backlog completo).

    Solo se calcula en el subdominio programación y para su personal
    (`request.es_personal_programacion`, que fija usuarios.middleware) → en el apex y en
    financiera no corre. Es un COUNT directo (barato), no arma las filas.
    """
    if getattr(request, 'area', None) != 'programacion':
        return {}
    if not getattr(request, 'es_personal_programacion', False):
        return {}
    from programacion.pagos.models import LotePagos, PagoRealizado
    n = (PagoRealizado.objects
         .filter(lote__estado=LotePagos.Estado.BORRADOR, excluida=False)
         .count())
    return {'pagos_por_revisar_count': n}
