from django.urls import path
from . import views

urlpatterns = [
    path('', views.ver_horario, name='ver_horario'),
    path('ajax/asignaturas/', views.obtener_asignaturas_personalizada, name='ajax_asignaturas_personalizada'),
    path('ajax/unidades/', views.obtener_unidades_personalizada, name='ajax_unidades_personalizada'),
    # Portal del profesor: bajo /profesores/ para no tocar _PERMITIDAS_PROFESOR.
    path('pagos/', views.mis_pagos, name='profesor_pagos'),
    path('pagos/soporte/<int:soporte_id>/', views.profesor_soporte_descargar, name='profesor_soporte_descargar'),
]