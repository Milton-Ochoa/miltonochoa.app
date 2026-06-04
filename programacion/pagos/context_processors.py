def pagos_por_revisar(request):
    """Contador para el badge del menú **Pagos** en programación: filas de la **semana
    actual** pendientes de revisar/enviar a financiera.

    Solo se calcula en el subdominio programación y para su personal
    (`request.es_personal_programacion`, que fija usuarios.middleware) → en el apex y en
    financiera no corre. Semántica: si la semana ya fue enviada → 0 (no hay nada que
    hacer); si está en borrador o sin preparar → número de filas no excluidas (lo que
    falta por enviar). Coste consciente: arma las filas de la semana en curso (igual que
    el badge de financiera); aceptable por ser solo esa ventana.
    """
    if getattr(request, 'area', None) != 'programacion':
        return {}
    if not getattr(request, 'es_personal_programacion', False):
        return {}
    from programacion.pagos.views import construir_contexto_pagos
    ctx = construir_contexto_pagos({}, modo='programacion')
    if ctx.get('estado_lote') == 'ENVIADO':
        return {'pagos_por_revisar_count': 0}
    n = sum(1 for f in ctx['filas_pendientes'] if not f.get('excluida'))
    return {'pagos_por_revisar_count': n}
