from django.apps import AppConfig


class AuditoriaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'programacion.auditoria'
    label = 'auditoria'
    # verbose_name no se define explícitamente; Django usa 'Auditoria' por defecto,
    # que es suficiente para el admin. Si se necesita cambiar, agregar aquí.
