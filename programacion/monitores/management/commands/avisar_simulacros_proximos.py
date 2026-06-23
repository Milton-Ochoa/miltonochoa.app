from django.core.management.base import BaseCommand

from programacion.monitores.avisos import notificar_simulacros_proximos


class Command(BaseCommand):
    """Envía por correo el resumen de simulacros próximos (≤7 días) sin monitor.

    Pensado para un scheduler (Railway Cron / cron externo) que lo corra a diario;
    no crea infraestructura de cron aquí. Sin simulacros próximos sin monitor no
    envía nada. Tolerante: un fallo de correo no rompe el comando (lo loguea).

    El destinatario sale de la env var ``MONITORES_NOTIFICAR_A``.
    """
    help = 'Avisa por correo de los simulacros próximos sin monitor asignado.'

    def handle(self, *args, **options):
        n = notificar_simulacros_proximos()
        if n:
            self.stdout.write(self.style.SUCCESS(
                f'Aviso enviado: {n} simulacro(s) próximos sin monitor.'))
        else:
            self.stdout.write('No hay simulacros próximos sin monitor; no se envió correo.')
