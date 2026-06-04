"""
Tests — app: exportar
Cobertura mínima de la página de exportación tras Calendario A/B (Fase 4):
el selector de colegios desambigua periodos con `periodo_label`.
"""
from datetime import date

from django.test import TestCase, Client
from django.contrib.auth.models import User

from programacion.configuracion.models import Colegio, ColegioAnio, Profesor
from programacion.exportar.models import (
    PagoRealizado, SoportePagoProfesor, _pago_soporte_upload_to,
)


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


class SoportePagoProfesorModelTest(TestCase):
    """El comprobante de pago se ata a un `PagoRealizado` y construye una ruta limpia."""

    def setUp(self):
        colegio = Colegio.objects.create(
            nombre='Colegio Central', departamento='Santander', ciudad='Bucaramanga')
        self.colegio_anio = ColegioAnio.objects.create(colegio=colegio, anio=2025)
        self.profesor = Profesor.objects.create(nombre='Ana María', apellido='Pérez Gómez')
        self.pago = PagoRealizado.objects.create(
            profesor=self.profesor, colegio=self.colegio_anio,
            fecha=date(2025, 3, 14), horas=2, valor=80000)

    def test_str_y_relacion(self):
        soporte = SoportePagoProfesor.objects.create(
            pago=self.pago, nombre_original='comprobante.pdf')
        self.assertEqual(list(self.pago.soportes.all()), [soporte])
        self.assertIn('comprobante.pdf', str(soporte))

    def test_upload_to_usa_docente_y_fecha(self):
        soporte = SoportePagoProfesor(pago=self.pago)
        ruta = _pago_soporte_upload_to(soporte, 'Recibo Original.PDF')
        self.assertEqual(ruta, 'pagos/pago-ana-perez-2025-03-14.pdf')
