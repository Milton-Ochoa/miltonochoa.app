from django.shortcuts import render, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.conf import settings
import logging
import threading

from .models import AlertaAuditoria
from .engine import sincronizar

logger = logging.getLogger('aamo')


@staff_member_required
def lista_alertas(request):
    """
    Vista principal del módulo de auditoría. Muestra alertas vigentes.

    Carga eager: cada visita ejecuta `sincronizar()` (con throttle interno de 5 min)
    en un hilo daemon y devuelve todas las alertas con vigente=True. El filtrado
    por tipo/colegio/descripción es client-side en el template, así que aquí no
    se aceptan GET params para filtrar.

    El hilo es daemon para que no impida el shutdown del servidor si falla.
    """
    def _sync_safe():
        # Wrapper con manejo de excepciones: los hilos daemon no propagan errores
        # al hilo principal, por lo que sin este try/except los fallos serían silenciosos.
        try:
            sincronizar()
        except Exception:
            logger.exception('Error en sincronizar auditoria (hilo bg)')
    if not getattr(settings, 'TESTING', False):
        threading.Thread(target=_sync_safe, daemon=True).start()

    alertas = (
        AlertaAuditoria.objects
        .filter(vigente=True)
        .select_related('colegio__colegio', 'profesor')
        .prefetch_related('colegios_implicados__colegio')
    )

    return render(request, 'auditoria/lista.html', {'alertas': alertas})


@staff_member_required
@require_POST
def ajax_ignorar_alerta(request, alerta_id):
    """
    Marca una alerta como ignorada manualmente por un administrador.

    Requiere un motivo de al menos 5 caracteres para que el cierre sea auditable:
    se quiere saber por qué se ignoró, no solo que se ignoró.
    El motivo queda registrado junto al usuario que lo hizo (`ignorado_por`).

    Solo acepta POST para evitar que una petición GET accidental (ej. prefetch
    del navegador) cierre alertas sin intención.
    """
    alerta = get_object_or_404(AlertaAuditoria, id=alerta_id)

    # Idempotencia: no tiene sentido ignorar algo que ya está resuelto/inactivo.
    if not alerta.vigente:
        return JsonResponse({'ok': False, 'error': 'La alerta ya está resuelta.'}, status=400)

    motivo = request.POST.get('motivo', '').strip()[:500]
    if len(motivo) < 5:
        return JsonResponse({'ok': False, 'error': 'El motivo debe tener al menos 5 caracteres.'}, status=400)

    alerta.vigente         = False
    alerta.resuelto_en     = timezone.now()
    alerta.motivo_ignorado = motivo
    alerta.ignorado_por    = request.user
    alerta.save(update_fields=['vigente', 'resuelto_en', 'motivo_ignorado', 'ignorado_por'])

    logger.info(
        'Alerta %s ignorada por %s. Motivo: %s',
        alerta_id, request.user.username, motivo[:100],
    )
    return JsonResponse({'ok': True})
