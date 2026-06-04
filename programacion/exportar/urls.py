from django.urls import path
from .views import (
    exportar_view, exportar_contar, exportar_pagos_view,
    pagos_detalle, soporte_descargar,
)

urlpatterns = [
    path('', exportar_view, name='exportar'),
    path('contar/', exportar_contar, name='exportar_contar'),
    path('pagos/', exportar_pagos_view, name='exportar_pagos'),
    path('pagos/<int:pago_id>/', pagos_detalle, name='pago_detalle'),
    path('pagos/soporte/<int:soporte_id>/descargar/', soporte_descargar, name='pago_soporte_descargar'),
]
