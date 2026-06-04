from django.urls import path

from . import views

urlpatterns = [
    path('', views.pagos_lista, name='pagos_lista'),

    # Revisión semanal (programación): preparar · enviar · reabrir
    path('preparar/', views.pagos_preparar_semana, name='pagos_preparar_semana'),
    path('enviar/', views.pagos_enviar_semana, name='pagos_enviar_semana'),
    path('reabrir/', views.pagos_desenviar_semana, name='pagos_desenviar_semana'),

    # Acciones por fila (BORRADOR): valor · excluir · extras
    path('<int:pago_id>/valor/', views.pagos_editar_valor, name='pagos_editar_valor'),
    path('<int:pago_id>/excluir/', views.pagos_excluir_fila, name='pagos_excluir_fila'),
    path('<int:pago_id>/extra/', views.pagos_agregar_extra, name='pagos_agregar_extra'),
    path('extra/<int:extra_id>/eliminar/', views.pagos_eliminar_extra, name='pagos_eliminar_extra'),

    path('<int:pago_id>/', views.pagos_detalle, name='pago_detalle'),
    path('soporte/<int:soporte_id>/descargar/', views.soporte_descargar, name='pago_soporte_descargar'),
]
