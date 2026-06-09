"""URLconf del **apex** (`miltonochoa.app`).

Es la entrada canónica de AAMO: login único, selector de área y administración.
Las áreas viven en sus propios subdominios (ver `core.urls_programacion` y
`core.middleware`), no aquí.
"""
from django.contrib import admin
from django.urls import path, include
from usuarios.ratelimit import rate_limit
from .views import seleccion_area, panel_admin, manifest_view, sw_view

# Handlers de error personalizados
handler404 = 'core.views.error_404'
handler500 = 'core.views.error_500'

# El login de /admin/ es el form propio de Django (no pasa por usuarios.vista_login):
# sin esto quedaría sin rate limit → fuerza bruta directa contra superusuarios.
# Debe asignarse ANTES de construir urlpatterns (admin.site.urls captura self.login).
admin.site.login = rate_limit(max_calls=10, periodo=60, respuesta='html')(admin.site.login)

urlpatterns = [
    # Punto de entrada AAMO: decide a qué área (subdominio) enviar al usuario.
    path('', seleccion_area, name='seleccion_area'),
    path('panel/', panel_admin, name='panel_admin'),
    path('admin/', admin.site.urls),

    # Login único / gestión de usuarios — GLOBAL, compartido por todas las áreas.
    path('usuarios/', include('usuarios.urls')),

    # PWA — recursos del origen apex (scope /).
    path('manifest.json', manifest_view, name='pwa_manifest'),
    path('sw.js', sw_view, name='pwa_sw'),
]
