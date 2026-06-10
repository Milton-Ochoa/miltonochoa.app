"""Aviso por correo a financiera cuando una solicitud de viáticos pasa a `ENVIADA`.

Se modela como un helper llamado desde las vistas (mismo patrón de "lógica directa
en las vistas" del resto de viáticos), no como signal. El envío debe ser tolerante
a fallos: un error de correo (Resend caído, credenciales mal) NUNCA debe tumbar el
guardado de la solicitud, así que se atrapa y se loguea.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail

from core.areas import url_en_area

logger = logging.getLogger('aamo')


def notificar_solicitud_enviada(solicitud, request):
    """Avisa a `VIATICOS_NOTIFICAR_A` que hay una solicitud por revisar.

    El enlace apunta al detalle en el área **financiera** (donde se gestiona). Se
    llama vía `transaction.on_commit` para no enviar si la transacción hace rollback.
    """
    asunto = f'Nueva solicitud de viáticos #{solicitud.pk} — {solicitud.docente_nombre}'

    detalle_url = url_en_area('financiera', 'fin_viaticos_detalle', request, pk=solicitud.pk)
    colegio = solicitud.colegio_nombre
    if solicitud.colegio_codigo:
        colegio = f'{solicitud.colegio_codigo} - {colegio}'

    cuerpo = (
        'Hay una nueva solicitud de viáticos pendiente de revisión en la plataforma.\n\n'
        f'Docente: {solicitud.docente_nombre}\n'
        f'Colegio: {colegio}\n'
        f'Fecha de viaje: {solicitud.fecha_viaje} — Regreso: {solicitud.fecha_regreso}\n'
        f'Total: ${solicitud.total:,.0f} COP\n\n'
        f'Revísala aquí: {detalle_url}\n'
    )

    try:
        send_mail(
            asunto,
            cuerpo,
            settings.DEFAULT_FROM_EMAIL,
            [settings.VIATICOS_NOTIFICAR_A],
            fail_silently=False,
        )
    except Exception:
        # No romper la petición del usuario por un fallo de correo.
        logger.exception('No se pudo enviar el aviso de viático #%s a financiera', solicitud.pk)


def notificar_legalizacion_enviada(solicitud, request):
    """Avisa a `VIATICOS_LEGALIZACION_NOTIFICAR_A` que hay una legalización por revisar.

    Mismo contrato que `notificar_solicitud_enviada`: se llama vía
    `transaction.on_commit` y un fallo de correo nunca tumba el guardado.
    """
    asunto = f'Legalización de viáticos #{solicitud.pk} — {solicitud.docente_nombre}'

    detalle_url = url_en_area('financiera', 'fin_viaticos_detalle', request, pk=solicitud.pk)
    colegio = solicitud.colegio_nombre
    if solicitud.colegio_codigo:
        colegio = f'{solicitud.colegio_codigo} - {colegio}'

    cuerpo = (
        'Programación envió la legalización de un viático pagado, pendiente de revisión.\n\n'
        f'Docente: {solicitud.docente_nombre}\n'
        f'Colegio: {colegio}\n'
        f'Fecha de viaje: {solicitud.fecha_viaje} — Regreso: {solicitud.fecha_regreso}\n'
        f'Total: ${solicitud.total:,.0f} COP\n\n'
        f'Revísala aquí: {detalle_url}\n'
    )

    try:
        send_mail(
            asunto,
            cuerpo,
            settings.DEFAULT_FROM_EMAIL,
            [settings.VIATICOS_LEGALIZACION_NOTIFICAR_A],
            fail_silently=False,
        )
    except Exception:
        logger.exception('No se pudo enviar el aviso de legalización del viático #%s', solicitud.pk)
