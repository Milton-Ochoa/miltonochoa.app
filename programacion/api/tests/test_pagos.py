"""
Tests del endpoint /api/v1/pagos/.
"""
from datetime import date
from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from programacion.configuracion.models import Colegio, ColegioAnio, Profesor
from programacion.pagos.models import PagoRealizado


def _setup():
    col = Colegio.objects.create(nombre='Col Pagos', departamento='Santander', ciudad='Buca')
    ca = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True, valor_hora=40000)
    prof = Profesor.objects.create(nombre='Pedro', apellido='Martínez')
    return ca, prof


class PagoListTest(TestCase):

    def setUp(self):
        self.client = APIClient(HTTP_HOST='programacion.testserver')
        self.user = User.objects.create_user(username='u', password='p', is_staff=True)
        self.client.force_authenticate(user=self.user)
        self.ca, self.prof = _setup()
        self.pago = PagoRealizado.objects.create(
            profesor=self.prof, colegio=self.ca,
            fecha=date(2026, 4, 5), horas=2.0, valor=80000,
            marcado_por=self.user,
        )

    def test_list_ok(self):
        resp = self.client.get('/api/v1/pagos/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 1)

    def test_fields_presentes(self):
        resp = self.client.get('/api/v1/pagos/')
        p = resp.data['results'][0]
        for f in ('id', 'fecha', 'horas', 'valor', 'fecha_pago',
                  'profesor_nombre', 'colegio_nombre', 'colegio_anio'):
            self.assertIn(f, p)

    def test_retrieve_ok(self):
        resp = self.client.get(f'/api/v1/pagos/{self.pago.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['valor'], 80000)

    def test_filtro_profesor(self):
        resp = self.client.get(f'/api/v1/pagos/?profesor={self.prof.id}')
        self.assertEqual(resp.data['count'], 1)

    def test_filtro_colegio(self):
        resp = self.client.get(f'/api/v1/pagos/?colegio={self.ca.id}')
        self.assertEqual(resp.data['count'], 1)

    def test_filtro_desde_hasta(self):
        resp = self.client.get('/api/v1/pagos/?desde=2026-04-01&hasta=2026-04-30')
        self.assertEqual(resp.data['count'], 1)

    def test_filtro_hasta_excluye(self):
        resp = self.client.get('/api/v1/pagos/?hasta=2026-03-31')
        self.assertEqual(resp.data['count'], 0)

    def test_create_pago_ok(self):
        prof2 = Profesor.objects.create(nombre='Clara', apellido='Ríos')
        resp = self.client.post('/api/v1/pagos/', {
            'profesor': prof2.id,
            'colegio': self.ca.id,
            'fecha': '2026-04-10',
            'horas': 1.5,
            'valor': 60000,
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(PagoRealizado.objects.filter(profesor=prof2).count(), 1)

    def test_create_pago_autofill_marcado_por(self):
        prof3 = Profesor.objects.create(nombre='Raúl', apellido='Silva')
        resp = self.client.post('/api/v1/pagos/', {
            'profesor': prof3.id,
            'colegio': self.ca.id,
            'fecha': '2026-04-11',
            'horas': 2.0,
            'valor': 80000,
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        pago = PagoRealizado.objects.get(profesor=prof3)
        self.assertEqual(pago.marcado_por, self.user)

    def test_create_pago_duplicado_400(self):
        resp = self.client.post('/api/v1/pagos/', {
            'profesor': self.prof.id,
            'colegio': self.ca.id,
            'fecha': '2026-04-05',
            'horas': 2.0,
            'valor': 80000,
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_create_pago_campos_faltantes_400(self):
        resp = self.client.post('/api/v1/pagos/', {'profesor': self.prof.id}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_delete_no_permitido(self):
        resp = self.client.delete(f'/api/v1/pagos/{self.pago.id}/')
        self.assertEqual(resp.status_code, 405)
