from django.urls import path
from . import views

urlpatterns = [
    path('cambiar-estado/<int:tarea_id>/<str:nuevo_estado>/', views.cambiar_estado, name='cambiar_estado'),
    path('editar-tarea/<int:tarea_id>/', views.editar_tarea, name='editar_tarea'),
]