"""
Tests — apps: general y core
Ambas apps no tienen modelos propios.
Se prueban las vistas básicas de acceso, PWA y caché.
"""
import json
from django.test import TestCase, Client
from django.core.cache import cache
from django.contrib.auth.models import User
from programacion.configuracion.models import Colegio, Profesor
from usuarios.models import UsuarioProfesor


class HomeViewTest(TestCase):

    def setUp(self):
        self.client = Client()

    def test_home_no_autenticado_redirige_a_login(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/configuracion/usuarios/login/', r['Location'])

    def test_home_admin_devuelve_200(self):
        User.objects.create_superuser(username='admin', password='pass')
        self.client.login(username='admin', password='pass')
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)


class GeneralViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(username='admin', password='pass')

    def test_no_autenticado_redirige_a_login(self):
        r = self.client.get('/general/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/configuracion/usuarios/login/', r['Location'])

    def test_admin_puede_acceder(self):
        self.client.login(username='admin', password='pass')
        r = self.client.get('/general/')
        self.assertEqual(r.status_code, 200)

    def test_usuario_profesor_no_puede_acceder_a_general(self):
        profesor = Profesor.objects.create(nombre='Test', apellido='Prof')
        user = User.objects.create_user(username='prof', password='pass')
        UsuarioProfesor.objects.create(user=user, profesor=profesor)
        self.client.login(username='prof', password='pass')
        r = self.client.get('/general/')
        # Middleware redirige al horario del profesor
        self.assertEqual(r.status_code, 302)
        self.assertIn(f'profesor_id={profesor.id}', r['Location'])

    def test_vista_general_cachea_html(self):
        """Segunda llamada devuelve exactamente el mismo HTML (desde caché)."""
        cache.clear()
        self.client.login(username='admin', password='pass')
        r1 = self.client.get('/general/?mes=4')
        r2 = self.client.get('/general/?mes=4')
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.content, r2.content)

    def test_vista_general_cache_distinta_por_mes(self):
        """Meses distintos producen respuestas independientes (sin colisión de clave)."""
        cache.clear()
        self.client.login(username='admin', password='pass')
        r_abr = self.client.get('/general/?mes=4')
        r_may = self.client.get('/general/?mes=5')
        self.assertEqual(r_abr.status_code, 200)
        self.assertEqual(r_may.status_code, 200)


class PWAViewsTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(username='admin_pwa', password='pass')
        self.anon_client = Client()

    def test_manifest_json_status_200_autenticado(self):
        self.client.login(username='admin_pwa', password='pass')
        r = self.client.get('/manifest.json')
        self.assertEqual(r.status_code, 200)

    def test_manifest_json_status_200_anonimo(self):
        """El navegador pide manifest.json sin sesión activa."""
        r = self.anon_client.get('/manifest.json')
        self.assertEqual(r.status_code, 200)

    def test_manifest_json_content_type(self):
        r = self.anon_client.get('/manifest.json')
        self.assertIn('application/manifest+json', r['Content-Type'])

    def test_manifest_json_campos_requeridos(self):
        r = self.anon_client.get('/manifest.json')
        data = json.loads(r.content)
        for campo in ('name', 'short_name', 'start_url', 'display', 'icons'):
            self.assertIn(campo, data, f'Falta campo: {campo}')
        self.assertTrue(len(data['icons']) > 0)
        self.assertEqual(data['start_url'], '/')

    def test_sw_js_status_200_anonimo(self):
        """El navegador registra el SW sin sesión activa."""
        r = self.anon_client.get('/sw.js')
        self.assertEqual(r.status_code, 200)

    def test_sw_js_content_type(self):
        r = self.anon_client.get('/sw.js')
        self.assertIn('application/javascript', r['Content-Type'])

    def test_sw_js_contiene_cache_name(self):
        r = self.anon_client.get('/sw.js')
        self.assertIn(b'aamo-v1', r.content)

    def test_sw_js_contiene_fetch_handler(self):
        r = self.anon_client.get('/sw.js')
        self.assertIn(b'fetch', r.content)
