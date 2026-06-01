from django.urls import path
from . import views

urlpatterns = [
    path('', views.ver_horario, name='ver_horario'),
    path('ajax/asignaturas/', views.obtener_asignaturas_particular, name='ajax_asignaturas_particular'),
    path('ajax/unidades/', views.obtener_unidades_particular, name='ajax_unidades_particular'),
]