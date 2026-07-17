"""Rutas de despachos (prefijo `/despachos/`, names `log_despachos_*`).

F2: carga del reporte. F3: tablero + detalle. F4: acciones POST (estado y cambio
de material por línea). El export llega en F5.
"""
from django.urls import path

from . import views

urlpatterns = [
    path('despachos/', views.tablero, name='log_despachos_tablero'),
    path('despachos/cargar/', views.cargar, name='log_despachos_cargar'),
    path('despachos/orden/<int:pk>/', views.orden_detalle, name='log_despachos_detalle'),
    # Acciones (F4)
    path('despachos/orden/<int:pk>/estado/', views.orden_estado,
         name='log_despachos_estado'),
    path('despachos/linea/<int:pk>/cambio/', views.linea_cambio,
         name='log_despachos_cambio'),
    path('despachos/linea/<int:pk>/cambio/quitar/', views.linea_cambio_quitar,
         name='log_despachos_cambio_quitar'),
    path('despachos/linea/<int:pk>/erp/', views.linea_erp_toggle,
         name='log_despachos_cambio_erp'),
]
