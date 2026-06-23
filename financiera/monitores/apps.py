from django.apps import AppConfig


class FinancieraMonitoresConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    # Ruta de import completa, pero label propio (sin modelos: usa los de
    # programacion.monitores). Mismo patrón que financiera.pagos / financiera.viaticos.
    name = 'financiera.monitores'
    label = 'fin_monitores'
