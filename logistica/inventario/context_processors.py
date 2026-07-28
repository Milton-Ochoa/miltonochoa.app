"""Context processor de los badges del menú de logística."""


def alertas_inventario(request):
    """Contadores para los badges del menú (`base_logistica.html`): artículos
    bajo mínimo (Existencias) y préstamos vencidos en ambas direcciones
    (Préstamos).

    Solo se calcula en peticiones del subdominio logistica y para su personal
    (`request.es_personal_logistica`, que fija usuarios.middleware) → en el
    apex y en las otras áreas no corre la query ni ensucia el contexto. Sin
    cache: son dos COUNTs baratos y el badge debe reflejar al instante lo que
    cambia una entrada o una devolución.
    """
    if getattr(request, 'area', None) != 'logistica':
        return {}
    if not getattr(request, 'es_personal_logistica', False):
        return {}
    from .permisos import bodega_asignada, es_restringido
    from .services import items_bajo_minimo, prestamos_vencidos
    datos = {
        'inv_bajo_minimo_count': items_bajo_minimo().count(),
        'inv_prestamos_vencidos_count': prestamos_vencidos().count(),
    }
    # Bodega que opera el usuario, para el aviso `_aviso_bodega.html` de los
    # formularios de escritura. Solo si está restringido (superusuario y quien
    # no tiene asignación escriben en todas → nada que avisar). El helper
    # memoiza en el objeto `user`, así que la vista no repite la consulta.
    usuario = getattr(request, 'user', None)
    if es_restringido(usuario):
        datos['inv_bodega_asignada'] = bodega_asignada(usuario)
    return datos
