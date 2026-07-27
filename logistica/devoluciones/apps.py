from django.apps import AppConfig


class LogisticaDevolucionesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'logistica.devoluciones'
    # Label propio (ruta de import ≠ app_label, convención del proyecto). Sin
    # modelos: los de la devolución viven en `logistica.inventario` porque la
    # escritura del ledger debe pasar por sus servicios.
    label = 'log_devoluciones'
