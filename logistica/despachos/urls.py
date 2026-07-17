"""Rutas de despachos (prefijo `/despachos/`, names `log_despachos_*`).

F2: carga del reporte. F3: tablero + detalle. Las acciones POST (estado, cambio
de material) y el export se añaden en F4/F5.
"""
from django.urls import path

from . import views

urlpatterns = [
    path('despachos/', views.tablero, name='log_despachos_tablero'),
    path('despachos/cargar/', views.cargar, name='log_despachos_cargar'),
    path('despachos/orden/<int:pk>/', views.orden_detalle, name='log_despachos_detalle'),
]
