from django.core.management.base import BaseCommand
from auditoria.engine import sincronizar


class Command(BaseCommand):
    """
    Ejecuta el motor de auditoría manualmente desde la línea de comandos.

    Uso principal:
      - Crons de producción (ej. Render Cron Jobs) para mantener alertas frescas
        sin depender de que un usuario navegue a la vista de auditoría.
      - Debugging: forzar una sincronización inmediata ignorando el throttle de caché.

    Siempre pasa forzar=True para saltarse el enfriamiento de 5 minutos que se
    aplica en las sincronizaciones automáticas desde la vista.
    """
    help = 'Ejecuta la auditoría y sincroniza alertas en la base de datos.'

    def handle(self, *args, **options):
        creadas, reactivadas, resueltas = sincronizar(forzar=True)
        self.stdout.write(self.style.SUCCESS(
            f'Auditoría completada: {creadas} nuevas, '
            f'{reactivadas} reactivadas, {resueltas} resueltas.'
        ))
