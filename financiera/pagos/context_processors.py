def pagos_pendientes(request):
    """Contador de filas de pago **pendientes de la semana actual** para el badge
    del menú financiera.

    Solo se calcula en el subdominio financiera y para su personal
    (`request.es_personal_financiera`, que fija usuarios.middleware) → en el apex y en
    programación no corre el cálculo. Reutiliza `construir_contexto_pagos` (semana por
    defecto = la actual) para que el conteo coincida exactamente con la pestaña
    Pendientes. Coste consciente: arma las filas de la semana en curso; aceptable por
    ser solo esa ventana.
    """
    if getattr(request, 'area', None) != 'financiera':
        return {}
    if not getattr(request, 'es_personal_financiera', False):
        return {}
    from programacion.pagos.views import construir_contexto_pagos
    # modo='financiera' → solo cuenta filas de lotes ENVIADO (lo que financiera realmente ve).
    ctx = construir_contexto_pagos({}, modo='financiera')
    return {'pagos_pendientes_count': len(ctx['filas_pendientes'])}
