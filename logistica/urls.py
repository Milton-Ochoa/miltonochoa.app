"""Rutas del área `logistica`, montadas en la raíz de su subdominio.

Espejo de `financiera/urls.py`: agrupa las sub-apps del área. El urlconf real
del host es `core.urls_logistica`, que incluye este módulo en `/`.
"""
from django.urls import path, include

urlpatterns = [
    path('', include('logistica.inventario.urls')),
    path('', include('logistica.personalizacion.urls')),
    path('', include('logistica.despachos.urls')),
]
