from django.urls import path

from . import views

urlpatterns = [
    path('',                            views.fin_home,             name='fin_home'),
    path('viaticos/',                   views.fin_viaticos_lista,   name='fin_viaticos_lista'),
    path('viaticos/<int:pk>/',          views.fin_viaticos_detalle, name='fin_viaticos_detalle'),
    path('viaticos/<int:pk>/editar/',   views.fin_viaticos_editar,  name='fin_viaticos_editar'),
    path('viaticos/<int:pk>/devolver/', views.fin_viaticos_devolver, name='fin_viaticos_devolver'),
    path('viaticos/<int:pk>/aprobar/',  views.fin_viaticos_aprobar, name='fin_viaticos_aprobar'),
    path('viaticos/<int:pk>/pagar/',    views.fin_viaticos_pagar,   name='fin_viaticos_pagar'),
    path('viaticos/<int:pk>/soporte/',  views.fin_viaticos_subir_soporte, name='fin_viaticos_subir_soporte'),
    path('viaticos/soporte/<int:soporte_id>/eliminar/', views.fin_viaticos_eliminar_soporte, name='fin_viaticos_eliminar_soporte'),
    path('viaticos/soporte/<int:soporte_id>/descargar/', views.fin_soporte_descargar, name='fin_soporte_descargar'),
]
