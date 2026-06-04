from django.apps import AppConfig


class FinancieraPagosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    # Ruta de import completa, pero label propio (sin modelos: usa los de
    # programacion.exportar). Mismo patrón que financiera.viaticos.
    name = 'financiera.pagos'
    label = 'fin_pagos'
