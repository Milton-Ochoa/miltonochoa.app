from django.contrib import admin
from django.urls import path, include
from .views import seleccion_area, manifest_view, sw_view

# Handlers de error personalizados
handler404 = 'core.views.error_404'
handler500 = 'core.views.error_500'

urlpatterns = [
    # Punto de entrada AAMO: decide a qué área enviar al usuario logueado.
    path('', seleccion_area, name='seleccion_area'),
    path('admin/', admin.site.urls),

    # Login único / gestión de usuarios — GLOBAL, compartido por todas las áreas.
    path('usuarios/', include('usuarios.urls')),

    # Áreas. Por ahora solo 'programacion'; logistica/financiera son placeholders.
    path('programacion/', include('programacion.urls')),

    # PWA — recursos globales servidos desde la raíz (scope /).
    path('manifest.json', manifest_view, name='pwa_manifest'),
    path('sw.js', sw_view, name='pwa_sw'),
]
