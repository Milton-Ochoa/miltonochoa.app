"""
Tests del endpoint /api/v1/colegios/ y /api/v1/colegios-anio/.
"""
from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from programacion.configuracion.models import Colegio, ColegioAnio


def _make_colegio(**kwargs):
    defaults = {'nombre': 'Colegio Test', 'departamento': 'Santander', 'ciudad': 'Bucaramanga'}
    defaults.update(kwargs)
    return Colegio.objects.create(**defaults)


class ColegioListTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='u', password='p', is_staff=True)
        self.client.force_authenticate(user=self.user)
        self.c1 = _make_colegio(nombre='Colegio Alfa', ciudad='Bucaramanga')
        self.c2 = _make_colegio(nombre='Colegio Beta', ciudad='Medellín', departamento='Antioquia')

    def test_list_ok(self):
        resp = self.client.get('/programacion/api/v1/colegios/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 2)

    def test_fields_presentes(self):
        resp = self.client.get('/programacion/api/v1/colegios/')
        col = resp.data['results'][0]
        for f in ('id', 'nombre', 'departamento', 'ciudad'):
            self.assertIn(f, col)

    def test_retrieve_ok(self):
        resp = self.client.get(f'/programacion/api/v1/colegios/{self.c1.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['nombre'], 'Colegio Alfa')

    def test_filtro_ciudad(self):
        resp = self.client.get('/programacion/api/v1/colegios/?ciudad=Medellín')
        self.assertEqual(resp.data['count'], 1)

    def test_search_nombre(self):
        resp = self.client.get('/programacion/api/v1/colegios/?search=Alfa')
        self.assertEqual(resp.data['count'], 1)

    def test_post_no_permitido(self):
        resp = self.client.post('/programacion/api/v1/colegios/', {'nombre': 'X'}, format='json')
        self.assertEqual(resp.status_code, 405)


class ColegioAnioListTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='u2', password='p', is_staff=True)
        self.client.force_authenticate(user=self.user)
        self.col = _make_colegio(nombre='Col X')
        self.ca1 = ColegioAnio.objects.create(colegio=self.col, anio=2025, activo=True, valor_hora=40000)
        self.ca2 = ColegioAnio.objects.create(colegio=self.col, anio=2026, activo=True, valor_hora=45000)

    def test_list_ok(self):
        resp = self.client.get('/programacion/api/v1/colegios-anio/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 2)

    def test_fields_presentes(self):
        resp = self.client.get('/programacion/api/v1/colegios-anio/')
        ca = resp.data['results'][0]
        for f in ('id', 'nombre', 'anio', 'valor_hora', 'activo'):
            self.assertIn(f, ca)

    def test_nombre_viene_de_colegio(self):
        resp = self.client.get(f'/programacion/api/v1/colegios-anio/{self.ca1.id}/')
        self.assertEqual(resp.data['nombre'], 'Col X')

    def test_filtro_anio(self):
        resp = self.client.get('/programacion/api/v1/colegios-anio/?anio=2025')
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['results'][0]['valor_hora'], 40000)

    def test_filtro_activo(self):
        ColegioAnio.objects.create(colegio=self.col, anio=2024, activo=False)
        resp = self.client.get('/programacion/api/v1/colegios-anio/?activo=true')
        self.assertEqual(resp.data['count'], 2)
