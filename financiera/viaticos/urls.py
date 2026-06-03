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
]
