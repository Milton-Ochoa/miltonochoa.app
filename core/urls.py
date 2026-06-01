from django.contrib import admin
from django.urls import path, include
from .views import historial_global, vista_general, ajax_busqueda_global, manifest_view, sw_view
from pendientes.views import kanban_inicio

# Handlers de error personalizados
handler404 = 'core.views.error_404'
handler500 = 'core.views.error_500'

urlpatterns = [
    path('', kanban_inicio, name='home'),
    path('admin/', admin.site.urls),
    path('configuracion/', include('configuracion.urls')),
    path('colegios/', include('colegios.urls')),
    path('profesores/', include('profesores.urls')),
    path('general/', vista_general, name='vista_general'),
    path('informes/', include('informes.urls')),
    path('auditoria/', include('auditoria.urls')),
    path('exportar/', include('exportar.urls')),
    path('historial/', historial_global, name='historial_global'),
    path('buscar/', ajax_busqueda_global, name='ajax_busqueda_global'),
    path('pendientes/', include('pendientes.urls')),
    path('api/v1/', include('api.urls')),
    path('manifest.json', manifest_view, name='pwa_manifest'),
    path('sw.js', sw_view, name='pwa_sw'),
]

