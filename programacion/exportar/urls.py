from django.urls import path
from .views import exportar_view, exportar_contar, exportar_pagos_view, ajax_marcar_pago

urlpatterns = [
    path('', exportar_view, name='exportar'),
    path('contar/', exportar_contar, name='exportar_contar'),
    path('pagos/', exportar_pagos_view, name='exportar_pagos'),
    path('pagos/marcar/', ajax_marcar_pago, name='ajax_marcar_pago'),
]
