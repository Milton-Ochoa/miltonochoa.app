from django.urls import path
from .views import (dashboard_colegios, cargar_grados, obtener_materias, obtener_unidades,
                    configurar_colegio, ajax_clonar_colegio, historial_colegio,
                    ajax_obtener_libros_especiales, ajax_guardar_clase, ajax_recalcular_secuencia,
                    ajax_panel_stats, ajax_panel_tabla)

urlpatterns = [
    path('', dashboard_colegios, name='dashboard'),
    path('ajax/cargar-grados/', cargar_grados, name='ajax_cargar_grados'),
    path('ajax/obtener-materias/', obtener_materias, name='ajax_obtener_materias'),
    path('ajax/obtener-unidades/', obtener_unidades, name='ajax_obtener_unidades'),
    path('ajax/libros-especiales/', ajax_obtener_libros_especiales, name='ajax_libros_especiales'),
    path('ajax/clonar/<int:colegio_id>/', ajax_clonar_colegio, name='ajax_clonar_colegio'),
    path('ajax/guardar-clase/<int:colegio_id>/', ajax_guardar_clase, name='ajax_guardar_clase'),
    path('ajax/recalcular-secuencia/<int:colegio_id>/', ajax_recalcular_secuencia, name='ajax_recalcular_secuencia'),
    path('ajax/panel-stats/<int:colegio_id>/', ajax_panel_stats, name='ajax_panel_stats'),
    path('ajax/panel-tabla/<int:colegio_id>/', ajax_panel_tabla, name='ajax_panel_tabla'),
    path('configurar-colegio/<int:colegio_id>/', configurar_colegio, name='configurar_colegio'),
    path('historial/<int:colegio_id>/', historial_colegio, name='historial_colegio'),
]