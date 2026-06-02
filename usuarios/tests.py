"""
Tests — app: usuarios
Modelos: UsuarioColegio, UsuarioProfesor
Vistas: vista_login, vista_logout, gestionar_usuarios, ajax_crear_usuario, ajax_resetear_password
Middleware: ControlAccesoMiddleware
"""
from django.test import TestCase, Client, RequestFactory
from django.contrib.auth.models import User
from django.core.cache import cache
from programacion.configuracion.models import Colegio, ColegioAnio, Profesor
from usuarios.models import UsuarioColegio, UsuarioProfesor
from usuarios.ratelimit import rate_limit


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
        r = self.client.get('/usuarios/logout/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r['Location'])

    def test_usuario_ya_autenticado_no_ve_el_login(self):
        self.client.login(username='admin', password='adminpass')
        r = self.client.get('/usuarios/login/')
        self.assertEqual(r.status_code, 302)


# ── AJAX crear / resetear ─────────────────────────────────────

class AjaxCrearUsuarioTest(TestCase):

    def setUp(self):
        self.client = Client()
        User.objects.create_superuser(username='admin', password='adminpass')
        self.client.login(username='admin', password='adminpass')
        self.colegio = Colegio.objects.create(nombre='Col Test', ciudad='Bogotá')
        self.profesor = Profesor.objects.create(nombre='Ana', apellido='García')

    def test_crear_usuario_colegio_retorna_password(self):
        r = self.client.post('/usuarios/ajax/crear/', {
            'tipo': 'colegio',
            'username': 'col_test',
            'colegio_id': self.colegio.id,
        })
        data = r.json()
        self.assertTrue(data['ok'])
        self.assertIn('password_inicial', data)
        self.assertGreater(len(data['password_inicial']), 6)
        self.assertTrue(User.objects.filter(username='col_test').exists())

    def test_crear_usuario_profesor_retorna_password(self):
        r = self.client.post('/usuarios/ajax/crear/', {
            'tipo': 'profesor',
            'username': 'prof_test',
            'profesor_id': self.profesor.id,
        })
        data = r.json()
        self.assertTrue(data['ok'])
        self.assertIn('password_inicial', data)

    def test_crear_usuario_duplicado_retorna_error(self):
        User.objects.create_user(username='existente', password='x')
        UsuarioColegio.objects.create(
            user=User.objects.get(username='existente'), colegio=self.colegio
        )
        r = self.client.post('/usuarios/ajax/crear/', {
            'tipo': 'colegio',
            'username': 'existente',
            'colegio_id': self.colegio.id,
        })
        data = r.json()
        self.assertFalse(data['ok'])

    def test_resetear_password_genera_nueva(self):
        user = User.objects.create_user(username='reset_test', password='antigua')
        perfil = UsuarioColegio.objects.create(user=user, colegio=self.colegio)
        r = self.client.post('/usuarios/ajax/resetear-password/', {
            'tipo': 'colegio',
            'perfil_id': perfil.id,
        })
        data = r.json()
        self.assertTrue(data['ok'])
        self.assertIn('nueva_password', data)
        # El hash debe haber cambiado
        user.refresh_from_db()
        self.assertTrue(user.check_password(data['nueva_password']))


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


# ── Rate Limiting ─────────────────────────────────────────────

class RateLimitTest(TestCase):

    def tearDown(self):
        cache.clear()

    def test_permite_llamadas_dentro_del_limite(self):
        factory = RequestFactory()

        @rate_limit(max_calls=3, periodo=60)
        def vista_test(request):
            from django.http import JsonResponse
            return JsonResponse({'ok': True})

        for _ in range(3):
            request = factory.get('/')
            request.META['REMOTE_ADDR'] = '127.0.0.1'
            r = vista_test(request)
            self.assertEqual(r.status_code, 200)

    def test_bloquea_cuando_supera_limite(self):
        factory = RequestFactory()

        @rate_limit(max_calls=2, periodo=60)
        def vista_test(request):
            from django.http import JsonResponse
            return JsonResponse({'ok': True})

        for _ in range(2):
            request = factory.get('/')
            request.META['REMOTE_ADDR'] = '10.0.0.1'
            vista_test(request)

        request = factory.get('/')
        request.META['REMOTE_ADDR'] = '10.0.0.1'
        r = vista_test(request)
        self.assertEqual(r.status_code, 429)
