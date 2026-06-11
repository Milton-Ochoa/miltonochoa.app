"""Tests de la Fase 1 del área logística: enrutado por subdominio, gating de
acceso (superusuario / grupo `area:logistica` / otros), selector de área, panel
del apex (alta/reseteo de empleados de logística) y toasts.

Patrón calcado de `financiera/viaticos/tests.py` (FinancieraAccesoTest):
`Client(HTTP_HOST='logistica.testserver')` para el área, host por defecto
`testserver` para el apex.
"""
from django.contrib.auth.models import User, Group
from django.contrib.messages import constants as msg_constants
from django.contrib.messages.storage.base import Message
from django.template.loader import render_to_string
from django.test import TestCase, Client, RequestFactory
from django.urls import set_urlconf

from core.areas import (
    GRUPO_STAFF_FINANCIERA, GRUPO_STAFF_LOGISTICA, GRUPO_STAFF_PROGRAMACION,
)
from usuarios.models import PerfilEmpleado


class LogisticaAccesoTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='logistica.testserver')
        # Los grupos los crean las migraciones 0004/0006/0009; en tests existen ya.
        self.grupo_log = Group.objects.get(name=GRUPO_STAFF_LOGISTICA)
        self.grupo_fin = Group.objects.get(name=GRUPO_STAFF_FINANCIERA)
        self.grupo_prog = Group.objects.get(name=GRUPO_STAFF_PROGRAMACION)

    def test_anonimo_redirige_a_login_apex(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/usuarios/login/', r['Location'])
        self.assertIn('next=', r['Location'])

    def test_superusuario_ve_inicio(self):
        User.objects.create_superuser(username='admin', password='pass')
        self.client.login(username='admin', password='pass')
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Logística AAMO')

    def test_staff_logistica_ve_inicio(self):
        u = User.objects.create_user(username='logis', password='pass')
        u.groups.add(self.grupo_log)
        self.client.login(username='logis', password='pass')
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Logística AAMO')

    def test_usuario_financiera_es_redirigido_al_selector(self):
        """Un usuario sin acceso a logística va al selector de área del apex,
        no se le hace logout (puede tener otra área)."""
        u = User.objects.create_user(username='finan', password='pass')
        u.groups.add(self.grupo_fin)
        self.client.login(username='finan', password='pass')
        r = self.client.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertNotIn('logistica.testserver', r['Location'])

    def test_usuario_programacion_es_redirigido_al_selector(self):
        u = User.objects.create_user(username='prog', password='pass')
        u.groups.add(self.grupo_prog)
        self.client.login(username='prog', password='pass')
        r = self.client.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertNotIn('logistica.testserver', r['Location'])

    def test_subdominio_no_registrado_sigue_dando_404(self):
        """`logistica` ya es un área registrada; el 404 de subdominio desconocido
        se conserva para cualquier otro subdominio."""
        c = Client(HTTP_HOST='bodega.testserver')
        r = c.get('/')
        self.assertEqual(r.status_code, 404)


class SeleccionAreaLogisticaTest(TestCase):
    """El selector del apex es genérico: con el grupo basta para listar/entrar."""

    def setUp(self):
        self.client = Client()  # apex: testserver
        self.grupo_log = Group.objects.get(name=GRUPO_STAFF_LOGISTICA)
        self.grupo_fin = Group.objects.get(name=GRUPO_STAFF_FINANCIERA)

    def test_usuario_solo_logistica_va_directo_a_su_subdominio(self):
        u = User.objects.create_user(username='logis', password='pass')
        u.groups.add(self.grupo_log)
        self.client.login(username='logis', password='pass')
        r = self.client.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('logistica.testserver', r['Location'])

    def test_usuario_dos_areas_ve_logistica_en_el_selector(self):
        u = User.objects.create_user(username='doble', password='pass')
        u.groups.add(self.grupo_log, self.grupo_fin)
        self.client.login(username='doble', password='pass')
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Logística')
        self.assertContains(r, 'Financiera')


class PanelAdminLogisticaTest(TestCase):
    """Gestión de empleados de logística desde el panel del apex (superusuario)."""

    def setUp(self):
        self.client = Client()  # apex
        User.objects.create_superuser(username='root', password='pass')
        self.client.login(username='root', password='pass')

    def _crear_empleado(self, username='emple_log'):
        return self.client.post('/usuarios/ajax/area/crear/', {
            'username': username,
            'email': f'{username}@ejemplo.com',
            'password': 'clave-generica-1',
            'area': 'logistica',
        })

    def test_panel_muestra_seccion_logistica(self):
        r = self.client.get('/panel/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Usuarios — Logística')

    def test_crear_empleado_logistica(self):
        r = self._crear_empleado()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])
        u = User.objects.get(username='emple_log')
        self.assertTrue(u.groups.filter(name=GRUPO_STAFF_LOGISTICA).exists())
        self.assertFalse(u.is_staff)
        perfil = PerfilEmpleado.objects.get(user=u)
        self.assertTrue(perfil.debe_cambiar_password)

    def test_area_desconocida_rechazada(self):
        r = self.client.post('/usuarios/ajax/area/crear/', {
            'username': 'x', 'email': 'x@e.com', 'password': 'clave-generica-1',
            'area': 'bodega',
        })
        self.assertEqual(r.status_code, 400)

    def test_resetear_password_vuelve_a_exigir_cambio(self):
        self._crear_empleado()
        u = User.objects.get(username='emple_log')
        PerfilEmpleado.objects.filter(user=u).update(debe_cambiar_password=False)
        r = self.client.post('/usuarios/ajax/area/resetear/', {
            'user_id': u.id, 'password': 'otra-clave-123',
        })
        self.assertTrue(r.json()['ok'])
        self.assertTrue(PerfilEmpleado.objects.get(user=u).debe_cambiar_password)

    def test_primer_ingreso_fuerza_cambio_de_password(self):
        """El empleado nuevo queda bloqueado en el área hasta elegir su clave."""
        self._crear_empleado()
        c = Client(HTTP_HOST='logistica.testserver')
        c.login(username='emple_log', password='clave-generica-1')
        r = c.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('cambiar', r['Location'])


class ToastLogisticaTest(TestCase):
    """El bloque de toasts de base_chrome.html debe emitir los messages en
    logística (como en programación) y seguir consumiéndolos sin mostrarlos en
    financiera. Se renderiza el template directamente con un request simulado
    porque la landing aún no dispara messages propios."""

    TEXTO = 'Operacion de prueba F1'

    def _render(self, template, area, urlconf):
        request = RequestFactory().get('/')
        request.area = area
        # Banderas que gatean los menús; los bloques de programación quedan inertes.
        request.es_personal_programacion = False
        request.es_personal_financiera = (area == 'financiera')
        request.es_personal_logistica = (area == 'logistica')
        mensajes = [Message(msg_constants.SUCCESS, self.TEXTO)]
        # {% url %} resuelve con el urlconf del thread (no hay request real).
        set_urlconf(urlconf)
        try:
            return render_to_string(template, {'request': request, 'messages': mensajes})
        finally:
            set_urlconf(None)

    def test_toast_presente_en_logistica(self):
        html = self._render('base_logistica.html', 'logistica', 'core.urls_logistica')
        self.assertIn(self.TEXTO, html)

    def test_toast_ausente_en_financiera(self):
        html = self._render('base_financiera.html', 'financiera', 'core.urls_financiera')
        self.assertNotIn(self.TEXTO, html)
