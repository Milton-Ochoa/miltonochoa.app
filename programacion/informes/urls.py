from django.urls import path
from . import views

# Prefijo aplicado en el URLconf raíz: /informes/
urlpatterns = [
    path('',                           views.lista_informes,  name='lista_informes'),
    path('<int:informe_id>/',          views.detalle_informe, name='detalle_informe'),
    path('ajax/obtener/',              views.obtener_informe, name='ajax_obtener_informe'),
    path('ajax/guardar/',              views.guardar_informe, name='ajax_guardar_informe'),
    path('<int:informe_id>/eliminar/', views.eliminar_informe, name='eliminar_informe'),
]
