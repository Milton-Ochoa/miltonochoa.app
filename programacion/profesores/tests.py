"""
Tests — app: profesores
Sin modelos propios. Prueba utilidades y vistas de profesores/views.py
"""
import json
from django.test import TestCase, Client
from django.contrib.auth.models import User
from datetime import date, time
from programacion.configuracion.models import Colegio, ColegioAnio, Profesor, NombreLibro, Materia, Unidad
from programacion.colegios.models import Asignacion, Clase, ClaseParticular, Grado
from usuarios.models import UsuarioProfesor
from programacion.profesores.views import extraer_minutos, _resolver_unidad, _libro_para_fecha
from collections import defaultdict


# ── Utilidades ────────────────────────────────────────────────

class ExtraerMinutosProfesorTest(TestCase):
    # profesores/views.py usa try/except — devuelve 0 (no 9999) para inválidos

    def test_hora_manana(self):
        self.assertEqual(extraer_minutos('8:00 - 10:00'), 480)

    def test_hora_tarde(self):
        self.assertEqual(extraer_minutos('14:30 - 16:30'), 870)

    def test_hora_invalida_devuelve_cero(self):
        self.assertEqual(extraer_minutos('sin hora'), 0)

    def test_cadena_vacia_devuelve_cero(self):
        self.assertEqual(extraer_minutos(''), 0)


class ResolverUnidadTest(TestCase):

    def test_unidad_sin_objeto_devuelve_texto(self):
        material, label, link = _resolver_unidad('A', None)
        self.assertIsNone(material)
        self.assertEqual(label, 'A')
        self.assertEqual(link, '#')

    def test_unidad_numerica_con_unidad_usa_datos_del_objeto(self):
        # Simulamos un objeto Unidad con los atributos que usa _resolver_unidad
        class FakeUnidad:
            nombre = 'Lectura profunda'
            link   = 'https://example.com/u3'

        material, label, link = _resolver_unidad('3', FakeUnidad())
        self.assertIsNone(material)
        self.assertIn('Lectura profunda', label)
        self.assertEqual(link, 'https://example.com/u3')

    def test_unidad_numerica_sin_libro_devuelve_defaults(self):
        material, label, link = _resolver_unidad('5', None)
        self.assertIsNone(material)
        self.assertEqual(label, '5')
        self.assertEqual(link, '#')


class LibroParaFechaTest(TestCase):

    def setUp(self):
        col = Colegio.objects.create(nombre='Col Libro', departamento='Santander', ciudad='BGA')
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)
        self.grado = Grado.objects.create(nombre='11-1')
        self.libro = NombreLibro.objects.create(nombre='Saberes 11 Oro')
        self.asig = Asignacion.objects.create(
            colegio=self.colegio, grado=self.grado, libro=self.libro,
            fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 12, 31),
        )
        self.mapa = defaultdict(list)
        self.mapa[(self.colegio.id, '11-1')].append(self.asig)

    def test_fecha_dentro_del_rango_devuelve_libro(self):
        r = _libro_para_fecha(self.mapa, self.colegio.id, '11-1', date(2026, 6, 15))
        self.assertEqual(r, 'Saberes 11 Oro')

    def test_fecha_fuera_del_rango_devuelve_sin_libro(self):
        r = _libro_para_fecha(self.mapa, self.colegio.id, '11-1', date(2025, 12, 31))
        self.assertEqual(r, 'Sin Libro')

    def test_colegio_o_grado_no_encontrado_devuelve_sin_libro(self):
        r = _libro_para_fecha(self.mapa, self.colegio.id, '9-1', date(2026, 3, 9))
        self.assertEqual(r, 'Sin Libro')


# ── Vistas ────────────────────────────────────────────────────

class VerHorarioViewTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.admin = User.objects.create_superuser(
            username='admin_prof', password='pass123'
        )
        self.profesor = Profesor.objects.create(nombre='Adrianis', apellido='Mercado')

    def test_no_autenticado_redirige_a_login(self):
        r = self.client.get('/profesores/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/usuarios/login/', r['Location'])

    def test_admin_puede_acceder_sin_profesor(self):
        self.client.login(username='admin_prof', password='pass123')
        r = self.client.get('/profesores/')
        self.assertEqual(r.status_code, 200)

    def test_admin_puede_acceder_con_profesor(self):
        self.client.login(username='admin_prof', password='pass123')
        r = self.client.get(f'/profesores/?profesor_id={self.profesor.id}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['profesor_sel'], str(self.profesor.id))

    def test_contexto_incluye_lista_de_profesores(self):
        self.client.login(username='admin_prof', password='pass123')
        r = self.client.get('/profesores/')
        self.assertIn('profesores', r.context)

    def test_usuario_profesor_no_puede_acceder_a_colegios(self):
        user = User.objects.create_user(username='adrianis', password='pass')
        UsuarioProfesor.objects.create(
            user=user, profesor=self.profesor
        )
        self.client.login(username='adrianis', password='pass')
        # El middleware bloquea /colegios/ y redirige a su horario
        r = self.client.get('/colegios/')
        self.assertEqual(r.status_code, 302)
        self.assertIn(f'profesor_id={self.profesor.id}', r['Location'])


class AjaxAsignaturasViewTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        User.objects.create_superuser(username='admin', password='pass')
        self.client.login(username='admin', password='pass')
        nombre_libro = NombreLibro.objects.create(nombre='Saberes 11 Oro', activo=True)
        materia_obj  = Materia.objects.create(nombre='Lectura Crítica')
        Unidad.objects.create(
            libro=nombre_libro, materia=materia_obj,
            numero=1, nombre='Primera unidad', link='https://example.com/u1'
        )
        Unidad.objects.create(
            libro=nombre_libro, materia=materia_obj,
            numero=2, nombre='Segunda unidad', link='https://example.com/u2'
        )

    def test_devuelve_materias_para_material_existente(self):
        r = self.client.get('/profesores/ajax/asignaturas/?material=Saberes 11 Oro')
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertIn('Lectura Crítica', data)

    def test_material_inexistente_devuelve_lista_vacia(self):
        r = self.client.get('/profesores/ajax/asignaturas/?material=Libro Inventado')
        data = json.loads(r.content)
        self.assertEqual(data, [])

    def test_sin_parametro_devuelve_lista_vacia(self):
        r = self.client.get('/profesores/ajax/asignaturas/')
        data = json.loads(r.content)
        self.assertEqual(data, [])


class AjaxUnidadesViewTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        User.objects.create_superuser(username='admin', password='pass')
        self.client.login(username='admin', password='pass')
        nombre_libro = NombreLibro.objects.create(nombre='Saberes 11 Oro', activo=True)
        materia_obj  = Materia.objects.create(nombre='Lectura Crítica')
        Unidad.objects.create(
            libro=nombre_libro, materia=materia_obj,
            numero=1, nombre='Primera', link='https://example.com'
        )

    def test_devuelve_unidades_para_material_y_materia_validos(self):
        r = self.client.get(
            '/profesores/ajax/unidades/?material=Saberes 11 Oro&materia=Lectura Crítica'
        )
        data = json.loads(r.content)
        self.assertTrue(len(data) > 0)
        self.assertIn('unidad', data[0])
        self.assertIn('nombre_unidad', data[0])

    def test_sin_parametros_devuelve_lista_vacia(self):
        r = self.client.get('/profesores/ajax/unidades/')
        data = json.loads(r.content)
        self.assertEqual(data, [])