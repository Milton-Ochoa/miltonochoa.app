"""Router del área **financiera**.

Agrupa las rutas del área en la **raíz** del subdominio `financiera.miltonochoa.app`
(montado en core/urls_financiera.py): `financiera.viaticos` (Inicio + gestión de
viáticos) y `financiera.pagos` (pagos de clases a profesores). Ambas sub-apps
montan en la raíz; sus rutas no colisionan (`''`/`viaticos/…` vs `pagos/…`).
"""
from django.urls import path, include

urlpatterns = [
    path('', include('financiera.viaticos.urls')),
    path('', include('financiera.pagos.urls')),
    path('', include('financiera.monitores.urls')),
]
