"""
Tests del endpoint /api/v1/clases/ y /api/v1/clases-particulares/.
"""
from datetime import date, time
from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from programacion.configuracion.models import Colegio, ColegioAnio, Profesor, Materia
from programacion.colegios.models import Grado, Bloque, Clase, ClaseParticular


def _setup_base():
    colegio = Colegio.objects.create(nombre='Col API', departamento='Santander', ciudad='Buca')
    ca = ColegioAnio.objects.create(colegio=colegio, anio=2026, activo=True, valor_hora=40000)
    grado = Grado.objects.create(nombre='10')
    bloque = Bloque.objects.create(
        colegio=ca, grado=grado,
        hora_inicio=time(8, 0), hora_fin=time(10, 0)
    )
    prof = Profesor.objects.create(nombre='Luis', apellido='Torres')
    materia = Materia.objects.create(nombre='Matemáticas', color='#00FF00')
    return ca, bloque, prof, materia


class ClaseListTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='u', password='p', is_staff=True)
        self.client.force_authenticate(user=self.user)
        self.ca, self.bloque, self.prof, self.materia = _setup_base()
        self.clase = Clase.objects.create(
            colegio=self.ca, bloque=self.bloque, fecha=date(2026, 4, 7),
            profesor=self.prof, materia=self.materia, unidad='1',
        )

    def test_list_ok(self):
        resp = self.client.get('/programacion/api/v1/clases/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 1)

    def test_fields_presentes(self):
        resp = self.client.get('/programacion/api/v1/clases/')
        c = resp.data['results'][0]
        for f in ('id', 'fecha', 'materia_nombre', 'profesor_nombre', 'colegio_nombre',
                  'colegio_anio', 'valor_hora', 'unidad', 'cancelada', 'grado', 'hora'):
            self.assertIn(f, c, f"Falta campo: {f}")

    def test_profesor_nombre_corto(self):
        resp = self.client.get(f'/programacion/api/v1/clases/{self.clase.id}/')
        self.assertEqual(resp.data['profesor_nombre'], 'Luis Torres')

    def test_valor_hora_correcto(self):
        resp = self.client.get(f'/programacion/api/v1/clases/{self.clase.id}/')
        self.assertEqual(resp.data['valor_hora'], 40000)

    def test_retrieve_ok(self):
        resp = self.client.get(f'/programacion/api/v1/clases/{self.clase.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['unidad'], '1')

    def test_filtro_colegio(self):
        resp = self.client.get(f'/programacion/api/v1/clases/?colegio={self.ca.id}')
        self.assertEqual(resp.data['count'], 1)

    def test_filtro_profesor_querystring(self):
        resp = self.client.get(f'/programacion/api/v1/clases/?profesor={self.prof.id}')
        self.assertEqual(resp.data['count'], 1)

    def test_filtro_desde_hasta(self):
        resp = self.client.get('/programacion/api/v1/clases/?desde=2026-04-01&hasta=2026-04-30')
        self.assertEqual(resp.data['count'], 1)

    def test_filtro_hasta_excluye(self):
        resp = self.client.get('/programacion/api/v1/clases/?hasta=2026-03-31')
        self.assertEqual(resp.data['count'], 0)

    def test_filtro_cancelada(self):
        Clase.objects.create(
            colegio=self.ca, bloque=Bloque.objects.create(
                colegio=self.ca, grado=self.bloque.grado,
                hora_inicio=time(10, 0), hora_fin=time(12, 0)
            ),
            fecha=date(2026, 4, 8), cancelada=True,
        )
        resp = self.client.get('/programacion/api/v1/clases/?cancelada=true')
        self.assertEqual(resp.data['count'], 1)

    def test_post_no_permitido(self):
        resp = self.client.post('/programacion/api/v1/clases/', {}, format='json')
        self.assertEqual(resp.status_code, 405)

    def test_clase_sin_profesor(self):
        clase2 = Clase.objects.create(
            colegio=self.ca,
            bloque=Bloque.objects.create(
                colegio=self.ca, grado=self.bloque.grado,
                hora_inicio=time(14, 0), hora_fin=time(16, 0)
            ),
            fecha=date(2026, 4, 9),
        )
        resp = self.client.get(f'/programacion/api/v1/clases/{clase2.id}/')
        self.assertIsNone(resp.data['profesor_nombre'])


class ClaseParticularListTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='u2', password='p', is_staff=True)
        self.client.force_authenticate(user=self.user)
        self.prof = Profesor.objects.create(nombre='María', apellido='López')
        self.grado = Grado.objects.create(nombre='9')
        self.materia = Materia.objects.create(nombre='Inglés', color='#0000FF')
        self.cp = ClaseParticular.objects.create(
            profesor=self.prof, grado=self.grado, materia=self.materia,
            estudiante='Colegio Ejemplo', ciudad='Bucaramanga',
            fecha=date(2026, 4, 10),
            hora_inicio=time(15, 0), hora_fin=time(17, 0),
            material='Libro X', unidad='1',
        )

    def test_list_ok(self):
        resp = self.client.get('/programacion/api/v1/clases-particulares/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 1)

    def test_fields_presentes(self):
        resp = self.client.get('/programacion/api/v1/clases-particulares/')
        cp = resp.data['results'][0]
        for f in ('id', 'fecha', 'hora_inicio', 'hora_fin', 'profesor_nombre', 'grado_nombre'):
            self.assertIn(f, cp)

    def test_filtro_profesor(self):
        resp = self.client.get(f'/programacion/api/v1/clases-particulares/?profesor={self.prof.id}')
        self.assertEqual(resp.data['count'], 1)

    def test_filtro_desde(self):
        resp = self.client.get('/programacion/api/v1/clases-particulares/?desde=2026-04-11')
        self.assertEqual(resp.data['count'], 0)
