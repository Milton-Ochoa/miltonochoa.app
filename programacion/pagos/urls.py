from django.urls import path

from . import views

urlpatterns = [
    path('', views.pagos_lista, name='pagos_lista'),

    # Revisión del backlog (programación): preparar pendientes · enviar visible
    path('preparar/', views.pagos_preparar, name='pagos_preparar'),
    path('enviar/', views.pagos_enviar, name='pagos_enviar'),

    # Acciones por fila (BORRADOR): excluir · extras
    path('<int:pago_id>/excluir/', views.pagos_excluir_fila, name='pagos_excluir_fila'),
    path('<int:pago_id>/extra/', views.pagos_agregar_extra, name='pagos_agregar_extra'),
    path('extra/<int:extra_id>/eliminar/', views.pagos_eliminar_extra, name='pagos_eliminar_extra'),

    path('<int:pago_id>/', views.pagos_detalle, name='pago_detalle'),
    path('soporte/<int:soporte_id>/descargar/', views.soporte_descargar, name='pago_soporte_descargar'),
]
