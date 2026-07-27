from django.apps import AppConfig


class FinancieraDevolucionesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    # Ruta de import completa, label propio y SIN modelos: la devolución vive en
    # `logistica.inventario` (única dueña del ledger). Mismo patrón que
    # financiera.pagos → programacion.pagos.
    name = 'financiera.devoluciones'
    label = 'fin_devoluciones'
