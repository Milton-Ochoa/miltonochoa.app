"""Tests del arranque del área financiera (Fase 3).

Verifican el enrutado por subdominio, el gating de acceso (superusuario / grupo
`area:financiera` / otros) y que el área programación sigue intacta tras el
refactor del chrome.
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User, Group

from core.areas import GRUPO_STAFF_FINANCIERA, GRUPO_STAFF_PROGRAMACION


class FinancieraAccesoTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='financiera.testserver')
        # Los grupos los crean las migraciones 0004/0006; en tests existen ya.
        self.grupo_fin = Group.objects.get(name=GRUPO_STAFF_FINANCIERA)
        self.grupo_prog = Group.objects.get(name=GRUPO_STAFF_PROGRAMACION)

    def test_anonimo_redirige_a_login_apex(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/usuarios/login/', r['Location'])

    def test_superusuario_ve_inicio(self):
        User.objects.create_superuser(username='admin', password='pass')
        self.client.login(username='admin', password='pass')
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Financiera AAMO')

    def test_staff_financiera_ve_inicio(self):
        u = User.objects.create_user(username='finan', password='pass')
        u.groups.add(self.grupo_fin)
        self.client.login(username='finan', password='pass')
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Financiera AAMO')

    def test_staff_financiera_ve_viaticos_placeholder(self):
        u = User.objects.create_user(username='finan2', password='pass')
        u.groups.add(self.grupo_fin)
        self.client.login(username='finan2', password='pass')
        r = self.client.get('/viaticos/')
        self.assertEqual(r.status_code, 200)

    def test_usuario_solo_programacion_es_redirigido(self):
        """Un usuario sin acceso a financiera va al selector de área del apex,
        no se le hace logout (puede tener otra área)."""
        u = User.objects.create_user(username='prog', password='pass')
        u.groups.add(self.grupo_prog)
        self.client.login(username='prog', password='pass')
        r = self.client.get('/')
        self.assertEqual(r.status_code, 302)
        # Redirige al apex (host sin el subdominio financiera).
        self.assertNotIn('financiera.testserver', r['Location'])


class SubdominioDesconocidoTest(TestCase):

    def test_subdominio_no_registrado_da_404(self):
        c = Client(HTTP_HOST='logistica.testserver')
        r = c.get('/')
        self.assertEqual(r.status_code, 404)


class ProgramacionIntactaTest(TestCase):
    """Tras el refactor del chrome (base_chrome.html), el área programación
    sigue cargando con su sidebar."""

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')

    def test_home_programacion_superusuario_ok(self):
        User.objects.create_superuser(username='admin', password='pass')
        self.client.login(username='admin', password='pass')
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Programación AAMO')
