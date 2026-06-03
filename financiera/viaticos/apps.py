from django.apps import AppConfig


class FinancieraViaticosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    # Ruta de import completa, pero label propio (sin modelos: importa los de
    # programacion.viaticos). Mismo patrón que las sub-apps de programación.
    name = 'financiera.viaticos'
    label = 'fin_viaticos'
