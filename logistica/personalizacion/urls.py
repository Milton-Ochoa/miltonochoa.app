"""Rutas de personalización (prefijo `/personalizacion/`, names
`log_personalizacion_*`).
"""
from django.urls import path

from . import views

urlpatterns = [
    path('personalizacion/', views.lista, name='log_personalizacion_lista'),
    path('personalizacion/generar/', views.generar,
         name='log_personalizacion_generar'),
    path('personalizacion/plantillas/subir/', views.plantilla_subir,
         name='log_personalizacion_subir'),
    path('personalizacion/plantillas/<int:pk>/eliminar/',
         views.plantilla_eliminar, name='log_personalizacion_eliminar'),
    path('personalizacion/plantillas/<int:pk>/descargar/',
         views.plantilla_descargar, name='log_personalizacion_descargar'),
]
