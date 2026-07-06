"""Rutas de personalización (prefijo `/personalizacion/`, names
`log_personalizacion_*`). La ruta de generación (Fase 3) se añade después.
"""
from django.urls import path

from . import views

urlpatterns = [
    path('personalizacion/', views.lista, name='log_personalizacion_lista'),
    path('personalizacion/plantillas/subir/', views.plantilla_subir,
         name='log_personalizacion_subir'),
    path('personalizacion/plantillas/<int:pk>/eliminar/',
         views.plantilla_eliminar, name='log_personalizacion_eliminar'),
    path('personalizacion/plantillas/<int:pk>/descargar/',
         views.plantilla_descargar, name='log_personalizacion_descargar'),
]
