"""URLconf del subdominio **logistica** (`logistica.miltonochoa.app`).

Espejo de `core.urls_financiera`: monta el área `logistica` en la **raíz** del
subdominio e incluye el login único (`usuarios`) y la PWA para que:
  - `{% url 'login' %}` / `{% url 'logout' %}` resuelvan localmente en las
    plantillas del área (la sesión se comparte vía cookie en `.miltonochoa.app`),
  - este origen sea una PWA instalable independiente.

El login canónico sigue siendo el del apex: `core.middleware` redirige aquí solo
a usuarios ya autenticados; los anónimos van al login del apex (ver
`usuarios.middleware`).
"""
from django.urls import path, include

from core.views import manifest_view, sw_view

handler404 = 'core.views.error_404'
handler500 = 'core.views.error_500'

urlpatterns = [
    # Login único / gestión de usuarios — mismos nombres y vistas que en el apex.
    path('usuarios/', include('usuarios.urls')),

    # PWA — recursos del origen del subdominio (scope /).
    path('manifest.json', manifest_view, name='pwa_manifest'),
    path('sw.js', sw_view, name='pwa_sw'),

    # Área logistica montada en la raíz del subdominio.
    path('', include('logistica.urls')),
]
