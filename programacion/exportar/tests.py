"""
Tests — app: exportar
Cobertura mínima de la página de exportación tras Calendario A/B (Fase 4):
el selector de colegios desambigua periodos con `periodo_label`.

(Los tests de pagos se movieron a `programacion/pagos/tests.py` al extraer esa sub-app.)
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User

from programacion.configuracion.models import Colegio, ColegioAnio


class ExportarSelectorPeriodoTest(TestCase):
    """El selector de colegios de la exportación muestra el periodo (A vs B)."""

    URL = '/exportar/'

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        User.objects.create_superuser(username='admin_exp', password='pass123')
        self.client.login(username='admin_exp', password='pass123')

    def test_lista_colegios_muestra_periodo_label(self):
        # Un colegio B y otro A, ambos con un periodo activo.
        col_b = Colegio.objects.create(
            nombre='Colegio Norte', departamento='Santander', ciudad='Bucaramanga',
            calendario=Colegio.Calendario.B)
        ColegioAnio.objects.create(colegio=col_b, anio=2025)
        col_a = Colegio.objects.create(
            nombre='Colegio Sur', departamento='Santander', ciudad='Bucaramanga',
            calendario=Colegio.Calendario.A)
        ColegioAnio.objects.create(colegio=col_a, anio=2025)

        html = self.client.get(self.URL).content.decode()
        # El B se ve como rango cruzado; el A como año natural.
        self.assertIn('2025-2026', html)
        self.assertIn('Colegio Norte', html)
        self.assertIn('Colegio Sur', html)
