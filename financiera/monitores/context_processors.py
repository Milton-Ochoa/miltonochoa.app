def pagos_monitores_pendientes(request):
    """Contador de pagos de monitores por pagar (todo el **backlog**) para el badge del
    menú financiera: COUNT directo de las filas enviadas y aún no pagadas (lote
    ENVIADO, `fecha_pago IS NULL`, no excluidas) — coincide con la pestaña Pendientes,
    que también es por backlog y no por semana. Espejo de
    ``financiera.pagos.context_processors.pagos_pendientes``.

    Solo se calcula en el subdominio financiera y para su personal
    (`request.es_personal_financiera`, que fija usuarios.middleware) → en el apex y en
    programación no corre el cálculo. Es un único COUNT indexado, no arma filas.
    """
    if getattr(request, 'area', None) != 'financiera':
        return {}
    if not getattr(request, 'es_personal_financiera', False):
        return {}
    from programacion.monitores.models import LoteMonitores, PagoMonitor
    n = (PagoMonitor.objects
         .filter(lote__estado=LoteMonitores.Estado.ENVIADO, excluida=False, fecha_pago__isnull=True)
         .count())
    return {'pagos_monitores_pendientes_count': n}
