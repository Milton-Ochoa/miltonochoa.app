"""Rutas de devoluciones de colegios (prefijo `/devoluciones/`, names
`log_devoluciones_*`).
"""
from django.urls import path

from . import views

urlpatterns = [
    path('devoluciones/', views.lista, name='log_devoluciones_lista'),
    path('devoluciones/nueva/', views.nueva, name='log_devoluciones_nueva'),
    path('devoluciones/detalle/', views.detallado,
         name='log_devoluciones_detallado'),
    path('devoluciones/exportar/', views.exportar,
         name='log_devoluciones_exportar'),
    # Después de las rutas fijas: `<int:pk>` no las capturaría, pero el orden
    # explícito evita sorpresas si mañana se añade un slug.
    path('devoluciones/<int:pk>/', views.detalle,
         name='log_devoluciones_detalle'),
]
