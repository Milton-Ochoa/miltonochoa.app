from django.urls import path

from . import views

urlpatterns = [
    path('',                 views.lista_viaticos,  name='viaticos_lista'),
    path('crear/',           views.crear_viatico,   name='viaticos_crear'),
    path('<int:pk>/',        views.detalle_viatico, name='viaticos_detalle'),
    path('<int:pk>/editar/', views.editar_viatico,  name='viaticos_editar'),
    path('soporte/<int:soporte_id>/', views.soporte_descargar, name='viaticos_soporte_descargar'),
    path('<int:pk>/legalizacion/soporte/', views.legalizacion_subir_soporte,
         name='viaticos_legalizacion_subir_soporte'),
    path('legalizacion/soporte/<int:soporte_id>/eliminar/', views.legalizacion_eliminar_soporte,
         name='viaticos_legalizacion_eliminar_soporte'),
    path('<int:pk>/legalizacion/enviar/', views.legalizacion_enviar,
         name='viaticos_legalizacion_enviar'),
]
