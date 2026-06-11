"""Router del área **programacion**.

Agrupa todas las sub-apps del área en la **raíz** del subdominio
`programacion.miltonochoa.app` (montado en core/urls_programacion.py). El home del
área (`kanban_inicio`) conserva el nombre de URL `home`, por lo que todas las
plantillas con `{% url 'home' %}` siguen apuntando al inicio del área sin cambios.

Las vistas transversales del área (vista_general, historial_global y la búsqueda
global) viven en core.views por motivos históricos; se referencian aquí para
mantenerlas dentro del namespace del área.
"""
from django.urls import path, include

from core.views import historial_global, vista_general, ajax_busqueda_global
from programacion.colegios.views import reporte_cancelaciones, reporte_cancelaciones_excel
from programacion.pendientes.views import kanban_inicio

urlpatterns = [
    path('', kanban_inicio, name='home'),
    # Bajo /reportes/ (NO /colegios/): el ControlAccesoMiddleware abre /colegios/
    # a los gestores de colegio; con este prefijo quedan bloqueados por middleware
    # y el gate es_personal_programacion de la vista es la segunda barrera.
    path('reportes/cancelaciones/', reporte_cancelaciones, name='reporte_cancelaciones'),
    path('reportes/cancelaciones/excel/', reporte_cancelaciones_excel, name='reporte_cancelaciones_excel'),
    path('configuracion/', include('programacion.configuracion.urls')),
    path('colegios/', include('programacion.colegios.urls')),
    path('profesores/', include('programacion.profesores.urls')),
    path('general/', vista_general, name='vista_general'),
    path('informes/', include('programacion.informes.urls')),
    path('auditoria/', include('programacion.auditoria.urls')),
    path('exportar/', include('programacion.exportar.urls')),
    path('pagos/', include('programacion.pagos.urls')),
    path('historial/', historial_global, name='historial_global'),
    path('buscar/', ajax_busqueda_global, name='ajax_busqueda_global'),
    path('pendientes/', include('programacion.pendientes.urls')),
    path('viaticos/', include('programacion.viaticos.urls')),
]
