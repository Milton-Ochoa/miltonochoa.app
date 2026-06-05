from django.urls import path
from . import views

urlpatterns = [
    path('', views.ver_horario, name='ver_horario'),
    path('ajax/asignaturas/', views.obtener_asignaturas_personalizada, name='ajax_asignaturas_personalizada'),
    path('ajax/unidades/', views.obtener_unidades_personalizada, name='ajax_unidades_personalizada'),
]