"""Rutas de devoluciones de colegios en financiera (solo lectura).

Mismo prefijo `/devoluciones/` que en logística —son subdominios distintos, no
colisionan— pero solo rutas de consulta: la lista, el detalle por material y el
export. No hay alta ni edición: registrar es competencia de logística.
"""
from django.urls import path

from . import views

urlpatterns = [
    path('devoluciones/', views.fin_devoluciones_lista,
         name='fin_devoluciones_lista'),
    path('devoluciones/detalle/', views.fin_devoluciones_detallado,
         name='fin_devoluciones_detallado'),
    path('devoluciones/exportar/', views.fin_devoluciones_exportar,
         name='fin_devoluciones_exportar'),
]
