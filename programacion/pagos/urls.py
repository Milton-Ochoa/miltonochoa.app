from django.urls import path

from . import views

urlpatterns = [
    path('', views.pagos_lista, name='pagos_lista'),
    path('<int:pago_id>/', views.pagos_detalle, name='pago_detalle'),
    path('soporte/<int:soporte_id>/descargar/', views.soporte_descargar, name='pago_soporte_descargar'),
]
