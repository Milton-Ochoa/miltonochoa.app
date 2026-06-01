from django.contrib import admin
from django.urls import path, include
from .views import historial_global, vista_general, ajax_busqueda_global, manifest_view, sw_view
from programacion.pendientes.views import kanban_inicio

# Handlers de error personalizados
handler404 = 'core.views.error_404'
handler500 = 'core.views.error_500'

urlpatterns = [
    path('', kanban_inicio, name='home'),
    path('admin/', admin.site.urls),
    path('configuracion/', include('programacion.configuracion.urls')),
    path('colegios/', include('programacion.colegios.urls')),
    path('profesores/', include('programacion.profesores.urls')),
    path('general/', vista_general, name='vista_general'),
    path('informes/', include('programacion.informes.urls')),
    path('auditoria/', include('programacion.auditoria.urls')),
    path('exportar/', include('programacion.exportar.urls')),
    path('historial/', historial_global, name='historial_global'),
    path('buscar/', ajax_busqueda_global, name='ajax_busqueda_global'),
    path('pendientes/', include('programacion.pendientes.urls')),
    path('api/v1/', include('programacion.api.urls')),
    path('manifest.json', manifest_view, name='pwa_manifest'),
    path('sw.js', sw_view, name='pwa_sw'),
]

