"""Context processor del badge de despachos en el menú de logística."""
from django.utils import timezone


def alertas_despachos(request):
    """Contador para el badge del ítem "Despachos" (`base_logistica.html`):
    órdenes **vencidas** = abiertas (PENDIENTE/ALISTADA), despachables y con
    `fecha_entrega` ya pasada.

    Solo corre en peticiones del subdominio logistica y para su personal
    (`request.es_personal_logistica`, que fija usuarios.middleware) → en el apex
    y en las otras áreas no ejecuta la query ni ensucia el contexto (patrón
    `alertas_inventario`). Sin cache: es un COUNT barato cubierto por el índice
    `(estado, fecha_entrega)` y el badge debe reflejar al instante lo que cambia
    una carga o una acción.
    """
    if getattr(request, 'area', None) != 'logistica':
        return {}
    if not getattr(request, 'es_personal_logistica', False):
        return {}
    from .models import OrdenDespacho
    return {
        'desp_vencidas_count': OrdenDespacho.objects.filter(
            estado__in=OrdenDespacho.ESTADOS_ABIERTOS,
            es_despachable=True,
            fecha_entrega__lt=timezone.localdate(),
        ).count(),
    }
