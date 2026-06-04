"""
Tests — app: pagos (sub-app propia, extraída de `exportar`).

Cubre el modelo de soporte y la vista de SOLO LECTURA de programación: ver el
detalle de un pago y sus soportes, pero sin poder marcar ni subir (eso es de
financiera).
"""
from datetime import date

from django.test import TestCase, Client
from django.contrib.auth.models import User

from programacion.configuracion.models import Colegio, ColegioAnio, Profesor
from programacion.pagos.models import (
    PagoRealizado, SoportePagoProfesor, _pago_soporte_upload_to,
)


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


class PagosProgramacionSoloLecturaTest(TestCase):
    """Programación ve el detalle del pago y sus soportes, pero NO puede marcar
    (esa acción se movió a financiera) ni subir comprobantes."""

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        User.objects.create_superuser(username='admin_prog', password='pass123')
        self.client.login(username='admin_prog', password='pass123')

        colegio = Colegio.objects.create(
            nombre='Colegio Central', departamento='Santander', ciudad='Bucaramanga')
        colegio_anio = ColegioAnio.objects.create(colegio=colegio, anio=2025)
        profesor = Profesor.objects.create(nombre='Ana', apellido='Pérez')
        self.pago = PagoRealizado.objects.create(
            profesor=profesor, colegio=colegio_anio,
            fecha=date(2025, 3, 14), horas=2, valor=80000)

    def test_detalle_solo_lectura_accesible(self):
        r = self.client.get(f'/pagos/{self.pago.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Soporte de pago')
        # Programación no muestra formulario de subida (lo gestiona financiera).
        self.assertNotContains(r, 'enctype="multipart/form-data"')

    def test_pagina_pagos_es_solo_lectura(self):
        r = self.client.get('/pagos/')
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'Marcar como pagado')

    def test_endpoint_marcar_ya_no_existe(self):
        # La ruta de marcar se retiró de programación (404).
        r = self.client.post('/pagos/marcar/', {
            'accion': 'marcar', 'profesor_id': self.pago.profesor_id,
            'colegio_id': self.pago.colegio_id, 'fecha': '2025-03-15',
            'horas': '2', 'valor': '80000',
        })
        self.assertEqual(r.status_code, 404)
