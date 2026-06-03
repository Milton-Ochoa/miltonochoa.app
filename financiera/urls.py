"""Router del área **financiera**.

Agrupa las rutas del área en la **raíz** del subdominio `financiera.miltonochoa.app`
(montado en core/urls_financiera.py). Por ahora todo cuelga de la sub-app
`financiera.viaticos` (Inicio + gestión de viáticos).
"""
from django.urls import path, include

urlpatterns = [
    path('', include('financiera.viaticos.urls')),
]
