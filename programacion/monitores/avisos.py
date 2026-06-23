"""Aviso de simulacros próximos sin monitor asignado.

Un simulacro sin monitores a menos de una semana es un riesgo operativo (no hay
quién vigile los salones). Este módulo concentra la consulta —reutilizada por el
badge del menú (context processor), el banner de la lista y el correo
automático— y el envío del correo. El envío es tolerante a fallos: un error de
correo NUNCA debe tumbar nada (el command es de scheduler, sin usuario).
"""
import logging

from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from core.areas import url_en_area

logger = logging.getLogger('aamo')

# Ventana de aviso: simulacros desde hoy hasta hoy+7 días (≈1 semana antes).
VENTANA_DIAS = 7


def simulacros_proximos_sin_monitor(hoy=None):
    """Queryset de simulacros con ``fecha`` entre hoy y hoy+``VENTANA_DIAS`` que
    **no** tienen ninguna ``AsignacionMonitor``. Ordenados por fecha ascendente
    (los más urgentes primero).

    Import diferido del modelo para que el módulo sea barato de importar (lo
    carga el context processor en cada request)."""
    from .models import Simulacro

    if hoy is None:
        hoy = timezone.localdate()
    hasta = hoy + timedelta(days=VENTANA_DIAS)
    return (Simulacro.objects
            .filter(fecha__range=(hoy, hasta), asignaciones__isnull=True)
            .order_by('fecha'))


def notificar_simulacros_proximos(request=None):
    """Envía al personal de programación (``MONITORES_NOTIFICAR_A``) el resumen de
    simulacros próximos sin monitor. Devuelve el número de simulacros avisados
    (0 = no se envió correo). Tolerante a fallos de correo.

    ``request`` es opcional: con él, el enlace a la lista apunta al subdominio
    de programación; sin él (ejecución por scheduler/command), se omite el enlace.
    """
    proximos = list(simulacros_proximos_sin_monitor())
    if not proximos:
        return 0

    lineas = []
    for s in proximos:
        grados = ', '.join(g.nombre for g in s.grados.all()) or 'sin grados'
        lineas.append(
            f'• {s.fecha:%d/%m/%Y} — {s.nombre_colegio} '
            f'({s.get_jornada_display()}, {grados})')

    cuerpo = (
        f'Hay {len(proximos)} simulacro(s) en los próximos {VENTANA_DIAS} días '
        'SIN monitores asignados:\n\n'
        + '\n'.join(lineas)
        + '\n\n'
    )
    if request is not None:
        cuerpo += f'Asígnalos aquí: {url_en_area("programacion", "simulacros_lista", request)}\n'

    asunto = f'⚠️ {len(proximos)} simulacro(s) próximos sin monitor'

    try:
        send_mail(
            asunto,
            cuerpo,
            settings.DEFAULT_FROM_EMAIL,
            [settings.MONITORES_NOTIFICAR_A],
            fail_silently=False,
        )
    except Exception:
        logger.exception('No se pudo enviar el aviso de simulacros próximos sin monitor')

    return len(proximos)
