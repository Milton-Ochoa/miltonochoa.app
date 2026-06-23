from django.urls import path

from .views import (configuracion_colegios_simulacro, configuracion_monitores,
                    colegios_simulacro_plantilla, simulacros_lista)

urlpatterns = [
    path('configuracion/', configuracion_monitores, name='configuracion_monitores'),
    path('colegios/', configuracion_colegios_simulacro,
         name='configuracion_colegios_simulacro'),
    path('colegios/plantilla/', colegios_simulacro_plantilla,
         name='colegios_simulacro_plantilla'),
    path('', simulacros_lista, name='simulacros_lista'),
]
