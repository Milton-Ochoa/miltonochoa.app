"""Rutas de despachos (prefijo `/despachos/`, names `log_despachos_*`).

F2: solo la carga del reporte. El tablero/detalle/acciones se añaden en F3/F4.
"""
from django.urls import path

from . import views

urlpatterns = [
    path('despachos/cargar/', views.cargar, name='log_despachos_cargar'),
]
