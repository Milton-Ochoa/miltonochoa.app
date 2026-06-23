from django.apps import AppConfig


class MonitoresConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    # Ruta de import completa; label corto (convención del proyecto: ruta ≠ label).
    name = 'programacion.monitores'
    label = 'monitores'
