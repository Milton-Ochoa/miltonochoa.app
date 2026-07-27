"""Rutas de devoluciones de colegios en financiera (solo lectura).

Mismo prefijo `/devoluciones/` que en logística —son subdominios distintos, no
colisionan— pero solo dos rutas: la lista y el export. No hay alta ni detalle:
registrar es competencia de logística.
"""
from django.urls import path

from . import views

urlpatterns = [
    path('devoluciones/', views.fin_devoluciones_lista,
         name='fin_devoluciones_lista'),
    path('devoluciones/exportar/', views.fin_devoluciones_exportar,
         name='fin_devoluciones_exportar'),
]
