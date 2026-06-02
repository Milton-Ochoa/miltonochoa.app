"""
Tests del endpoint /api/v1/profesores/.
"""
from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from programacion.configuracion.models import Profesor, Materia


def _make_profesor(**kwargs):
    defaults = {'nombre': 'Ana', 'apellido': 'García', 'ciudad': 'Bogotá', 'departamento': 'Cundinamarca'}
    defaults.update(kwargs)
    return Profesor.objects.create(**defaults)


class ProfesorListTest(TestCase):

    def setUp(self):
        self.client = APIClient(HTTP_HOST='programacion.testserver')
        self.user = User.objects.create_user(username='u', password='p', is_staff=True)
        self.client.force_authenticate(user=self.user)
        self.p1 = _make_profesor(nombre='Ana', apellido='García', ciudad='Bogotá')
        self.p2 = _make_profesor(nombre='Juan', apellido='Pérez', ciudad='Medellín',
                                  departamento='Antioquia', documento='123456')

    def test_list_ok(self):
        resp = self.client.get('/api/v1/profesores/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 2)

    def test_fields_presentes(self):
        resp = self.client.get('/api/v1/profesores/')
        profesor = resp.data['results'][0]
        for campo in ('id', 'nombre', 'apellido', 'nombre_corto', 'materias_nombres'):
            self.assertIn(campo, profesor, f"Falta campo: {campo}")

    def test_nombre_corto_calculado(self):
        resp = self.client.get(f'/api/v1/profesores/{self.p2.id}/')
        self.assertEqual(resp.data['nombre_corto'], 'Juan Pérez')

    def test_nombre_corto_sin_apellido(self):
        p = _make_profesor(nombre='Carlos', apellido=None, ciudad='Cali', departamento='Valle')
        resp = self.client.get(f'/api/v1/profesores/{p.id}/')
        self.assertEqual(resp.data['nombre_corto'], 'Carlos')

    def test_retrieve_ok(self):
        resp = self.client.get(f'/api/v1/profesores/{self.p1.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['nombre'], 'Ana')

    def test_retrieve_no_existe_404(self):
        resp = self.client.get('/api/v1/profesores/99999/')
        self.assertEqual(resp.status_code, 404)

    def test_filtro_ciudad(self):
        resp = self.client.get('/api/v1/profesores/?ciudad=Medellín')
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['results'][0]['nombre'], 'Juan')

    def test_filtro_departamento(self):
        resp = self.client.get('/api/v1/profesores/?departamento=Cundinamarca')
        self.assertEqual(resp.data['count'], 1)

    def test_search_nombre(self):
        resp = self.client.get('/api/v1/profesores/?search=Ana')
        self.assertEqual(resp.data['count'], 1)

    def test_search_documento(self):
        resp = self.client.get('/api/v1/profesores/?search=123456')
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['results'][0]['nombre'], 'Juan')

    def test_materias_nombres_lista(self):
        mat = Materia.objects.create(nombre='Física', color='#FF0000')
        self.p1.materias.add(mat)
        resp = self.client.get(f'/api/v1/profesores/{self.p1.id}/')
        self.assertIn('Física', resp.data['materias_nombres'])

    def test_post_no_permitido(self):
        resp = self.client.post('/api/v1/profesores/', {'nombre': 'X'}, format='json')
        self.assertEqual(resp.status_code, 405)
