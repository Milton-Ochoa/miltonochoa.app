from django.urls import path

from . import views

urlpatterns = [
    path('',                 views.lista_viaticos,  name='viaticos_lista'),
    path('crear/',           views.crear_viatico,   name='viaticos_crear'),
    path('<int:pk>/',        views.detalle_viatico, name='viaticos_detalle'),
    path('<int:pk>/editar/', views.editar_viatico,  name='viaticos_editar'),
]
