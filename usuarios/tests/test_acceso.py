"""
Tests — app: usuarios (acceso)
Modelos: UsuarioColegio, UsuarioProfesor
Vistas: vista_login, vista_logout, cambio de password obligatorio, password reset
Middleware: ControlAccesoMiddleware
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User, Group
from programacion.configuracion.models import Colegio, ColegioAnio, Profesor
from usuarios.models import UsuarioColegio, UsuarioProfesor, PerfilEmpleado
from core.areas import GRUPO_STAFF_PROGRAMACION


# ── Modelos ───────────────────────────────────────────────────

class UsuarioColegioModelTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='user_col', password='pass123')
        self.colegio = Colegio.objects.create(nombre='Colegio Demo', ciudad='Bogotá')
        self.perfil = UsuarioColegio.objects.create(user=self.user, colegio=self.colegio)

    def test_str_incluye_username_y_colegio(self):
        r = str(self.perfil)
        self.assertIn('user_col', r)
        self.assertIn('Colegio Demo', r)

    def test_relacion_one_to_one_desde_user(self):
        self.assertEqual(self.user.perfil_colegio, self.perfil)

    def test_un_user_no_puede_tener_dos_perfiles_colegio(self):
        from django.db import IntegrityError
        colegio2 = Colegio.objects.create(nombre='Otro Colegio', ciudad='Cali')
        with self.assertRaises(IntegrityError):
            UsuarioColegio.objects.create(user=self.user, colegio=colegio2)


class UsuarioProfesorModelTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='user_prof', password='pass456')
        self.profesor = Profesor.objects.create(nombre='Carlos', apellido='López')
        self.perfil = UsuarioProfesor.objects.create(user=self.user, profesor=self.profesor)

    def test_str_incluye_username_y_profesor(self):
        r = str(self.perfil)
        self.assertIn('user_prof', r)
        self.assertIn('Carlos', r)

    def test_relacion_one_to_one_desde_user(self):
        self.assertEqual(self.user.perfil_profesor, self.perfil)


# ── Vistas de autenticación ───────────────────────────────────

class LoginViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        User.objects.create_superuser(username='admin', password='adminpass')

    def test_get_login_devuelve_200(self):
        r = self.client.get('/usuarios/login/')
        self.assertEqual(r.status_code, 200)

    def test_login_correcto_redirige(self):
        r = self.client.post('/usuarios/login/', {
            'username': 'admin', 'password': 'adminpass'
        })
        self.assertEqual(r.status_code, 302)

    def test_login_incorrecto_muestra_error(self):
        r = self.client.post('/usuarios/login/', {
            'username': 'admin', 'password': 'clave_incorrecta'
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'incorrectos')

    def test_logout_redirige_a_login(self):
        self.client.login(username='admin', password='adminpass')
        # vista_logout es @require_POST (las plantillas envían POST con CSRF).
        r = self.client.post('/usuarios/logout/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r['Location'])

    def test_usuario_ya_autenticado_no_ve_el_login(self):
        self.client.login(username='admin', password='adminpass')
        r = self.client.get('/usuarios/login/')
        self.assertEqual(r.status_code, 302)


# ── Middleware de control de acceso ───────────────────────────

class MiddlewareAccesoTest(TestCase):

    def setUp(self):
        # El control de acceso por rol actúa dentro del subdominio del área.
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.colegio_perm = Colegio.objects.create(
            nombre='Col MW', departamento='Santander', ciudad='BGA'
        )
        self.colegio_anio = ColegioAnio.objects.create(
            colegio=self.colegio_perm, anio=2026, activo=True
        )
        self.profesor = Profesor.objects.create(nombre='Pedro', apellido='López')
        user_col = User.objects.create_user('user_col_mw', password='pass')
        UsuarioColegio.objects.create(user=user_col, colegio=self.colegio_perm)
        user_prof = User.objects.create_user('user_prof_mw', password='pass')
        UsuarioProfesor.objects.create(user=user_prof, profesor=self.profesor)

    def test_usuario_no_autenticado_redirige_a_login(self):
        # Anónimo en un subdominio de área → login canónico del apex con ?next= absoluto.
        r = self.client.get('/colegios/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/usuarios/login/', r['Location'])
        self.assertIn('next=', r['Location'])
        self.assertIn('colegios', r['Location'])

    def test_usuario_colegio_no_accede_a_configuracion(self):
        self.client.login(username='user_col_mw', password='pass')
        r = self.client.get('/configuracion/libros/')
        self.assertEqual(r.status_code, 302)
        self.assertNotIn('/configuracion/', r['Location'])

    def test_usuario_profesor_no_accede_a_colegios(self):
        self.client.login(username='user_prof_mw', password='pass')
        r = self.client.get('/colegios/')
        self.assertEqual(r.status_code, 302)

    def test_usuario_colegio_accede_a_su_propio_colegio(self):
        self.client.login(username='user_col_mw', password='pass')
        r = self.client.get(f'/colegios/?id_col={self.colegio_anio.id}')
        self.assertEqual(r.status_code, 200)


# ── Cambio obligatorio en el primer ingreso (empleados de área) ──

class CambioPasswordObligatorioTest(TestCase):

    def setUp(self):
        self.area_client = Client(HTTP_HOST='programacion.testserver')
        self.grupo, _ = Group.objects.get_or_create(name=GRUPO_STAFF_PROGRAMACION)
        self.user = User.objects.create_user('emp_force', password='generica', email='f@e.com')
        self.user.groups.add(self.grupo)
        PerfilEmpleado.objects.create(user=self.user, debe_cambiar_password=True)
        self.area_client.login(username='emp_force', password='generica')

    def test_empleado_con_flag_es_redirigido(self):
        r = self.area_client.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/usuarios/cambiar-password/', r['Location'])

    def test_pagina_de_cambio_es_accesible(self):
        r = self.area_client.get('/usuarios/cambiar-password/')
        self.assertEqual(r.status_code, 200)

    def test_cambiar_password_limpia_flag_y_da_acceso(self):
        r = self.area_client.post('/usuarios/cambiar-password/', {
            'new_password1': 'ClaveElegida88', 'new_password2': 'ClaveElegida88',
        })
        self.assertEqual(r.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('ClaveElegida88'))
        self.assertFalse(self.user.perfil_empleado.debe_cambiar_password)
        # Ya no se le fuerza el cambio: accede al home del área.
        self.assertEqual(self.area_client.get('/').status_code, 200)

    def test_password_debil_es_rechazada(self):
        r = self.area_client.post('/usuarios/cambiar-password/', {
            'new_password1': '123', 'new_password2': '123',
        })
        self.assertEqual(r.status_code, 200)  # re-renderiza con errores
        self.user.refresh_from_db()
        self.assertTrue(self.user.perfil_empleado.debe_cambiar_password)


class PasswordResetEmpleadoTest(TestCase):
    """El auto-servicio "olvidé mi contraseña" limpia el flag de cambio forzado."""

    def setUp(self):
        self.client = Client()  # apex
        self.grupo, _ = Group.objects.get_or_create(name=GRUPO_STAFF_PROGRAMACION)
        self.user = User.objects.create_user('emp_reset', password='vieja', email='emp@e.com')
        self.user.groups.add(self.grupo)
        PerfilEmpleado.objects.create(user=self.user, debe_cambiar_password=True)

    def test_envia_correo_con_enlace(self):
        from django.core import mail
        r = self.client.post('/usuarios/reset/', {'email': 'emp@e.com'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/usuarios/reset/', mail.outbox[0].body)

    def test_confirmar_enlace_limpia_flag(self):
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes
        from django.contrib.auth.tokens import default_token_generator
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        # GET fija el token en sesión y redirige al formulario set-password.
        r = self.client.get(f'/usuarios/reset/{uid}/{token}/')
        self.assertEqual(r.status_code, 302)
        r2 = self.client.post(r.url, {
            'new_password1': 'MiClaveNueva77', 'new_password2': 'MiClaveNueva77',
        })
        self.assertEqual(r2.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('MiClaveNueva77'))
        self.assertFalse(self.user.perfil_empleado.debe_cambiar_password)
