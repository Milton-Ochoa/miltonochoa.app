from django.apps import AppConfig


class LogisticaDespachosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'logistica.despachos'
    # Label propio (ruta de import ≠ app_label, convención del proyecto). Las
    # tablas del área usan el prefijo 'log_' en su Meta.db_table.
    label = 'log_despachos'
