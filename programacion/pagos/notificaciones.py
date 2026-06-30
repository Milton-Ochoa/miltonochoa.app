"""Aviso por correo a financiera cuando programación envía pagos a profesores.

Mismo patrón que los viáticos (`programacion/viaticos/notificaciones.py`): un helper
llamado desde la vista, no un signal. El envío es **tolerante a fallos**: un error de
correo (Resend caído, credenciales mal) NUNCA debe tumbar el envío de los lotes, así
que se atrapa y se loguea.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail

from core.areas import url_en_area

logger = logging.getLogger('aamo')


def notificar_pagos_enviados(lotes, request):
    """Avisa a `PAGOS_NOTIFICAR_A` que programación envió pagos a profesores.

    `lotes` son los `LotePagos` que pasaron a ENVIADO en esta acción. Se manda un
    único correo resumen (no uno por semana) con el conteo, las semanas y el total,
    y un enlace al listado de pagos en el área **financiera** (donde se gestionan).
    """
    if not lotes:
        return

    n = len(lotes)
    total = 0
    lineas_semana = []
    for lote in lotes:
        subtotal = sum(p.total for p in lote.filas.all())
        total += subtotal
        lineas_semana.append(
            f'  · {lote.fecha_inicio} a {lote.fecha_fin}: ${subtotal:,.0f} COP'
        )

    lista_url = url_en_area('financiera', 'fin_pagos_lista', request)

    asunto = f'Programación envió pagos a profesores ({n} semana(s))'
    cuerpo = (
        'Programación envió pagos a profesores a financiera para su gestión.\n\n'
        f'Semanas enviadas: {n}\n'
        + '\n'.join(lineas_semana)
        + f'\n\nTotal enviado: ${total:,.0f} COP\n\n'
        f'Revísalos aquí: {lista_url}\n'
    )

    try:
        send_mail(
            asunto,
            cuerpo,
            settings.DEFAULT_FROM_EMAIL,
            [settings.PAGOS_NOTIFICAR_A],
            fail_silently=False,
        )
    except Exception:
        # No romper el envío de los lotes por un fallo de correo.
        logger.exception('No se pudo enviar el aviso de pagos a financiera (%s lote(s))', n)
