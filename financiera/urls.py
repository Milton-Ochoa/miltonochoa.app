"""Router del área **financiera**.

Agrupa las rutas del área en la **raíz** del subdominio `financiera.miltonochoa.app`
(montado en core/urls_financiera.py): `financiera.viaticos` (Inicio + gestión de
viáticos), `financiera.pagos` (pagos de clases a profesores), `financiera.monitores`
y `financiera.devoluciones` (consulta de las devoluciones de colegios que registra
logística). Todas montan en la raíz; sus rutas no colisionan (`''`/`viaticos/…` vs
`pagos/…` vs `monitores/…` vs `devoluciones/…`).
"""
from django.urls import path, include

urlpatterns = [
    path('', include('financiera.viaticos.urls')),
    path('', include('financiera.pagos.urls')),
    path('', include('financiera.monitores.urls')),
    path('', include('financiera.devoluciones.urls')),
]
