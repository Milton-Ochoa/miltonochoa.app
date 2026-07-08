"""
Tests — app: usuarios
Modelos: UsuarioColegio, UsuarioProfesor
Vistas: vista_login, vista_logout, gestionar_usuarios, ajax_crear_usuario, ajax_resetear_password
Middleware: ControlAccesoMiddleware
"""
from django.test import TestCase, Client, RequestFactory
from django.contrib.auth.models import User, Group
from django.core.cache import cache
from programacion.configuracion.models import Colegio, ColegioAnio, Profesor
from usuarios.models import UsuarioColegio, UsuarioProfesor, PerfilEmpleado, ErrorCliente
from usuarios.ratelimit import rate_limit
from core.areas import GRUPO_STAFF_PROGRAMACION
import json


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


# ── AJAX crear / resetear ─────────────────────────────────────

class AjaxCrearUsuarioTest(TestCase):

    def setUp(self):
        self.client = Client()
        User.objects.create_superuser(username='admin', password='adminpass')
        self.client.login(username='admin', password='adminpass')
        self.colegio = Colegio.objects.create(nombre='Col Test', ciudad='Bogotá')
        self.profesor = Profesor.objects.create(nombre='Ana', apellido='García')

    def test_crear_usuario_colegio_con_password_manual(self):
        r = self.client.post('/usuarios/ajax/crear/', {
            'tipo': 'colegio',
            'username': 'col_test',
            'password': 'ClaveManual123',
            'colegio_id': self.colegio.id,
        })
        data = r.json()
        self.assertTrue(data['ok'])
        self.assertNotIn('password_inicial', data)  # ya no se devuelve: el admin la asignó
        user = User.objects.get(username='col_test')
        self.assertTrue(user.check_password('ClaveManual123'))

    def test_crear_usuario_profesor_con_password_manual(self):
        r = self.client.post('/usuarios/ajax/crear/', {
            'tipo': 'profesor',
            'username': 'prof_test',
            'password': 'OtraClave456',
            'profesor_id': self.profesor.id,
        })
        data = r.json()
        self.assertTrue(data['ok'])
        self.assertTrue(User.objects.get(username='prof_test').check_password('OtraClave456'))

    def test_crear_usuario_sin_password_falla(self):
        r = self.client.post('/usuarios/ajax/crear/', {
            'tipo': 'colegio',
            'username': 'col_sin_pass',
            'colegio_id': self.colegio.id,
        })
        self.assertFalse(r.json()['ok'])
        self.assertFalse(User.objects.filter(username='col_sin_pass').exists())

    def test_crear_usuario_duplicado_retorna_error(self):
        User.objects.create_user(username='existente', password='x')
        UsuarioColegio.objects.create(
            user=User.objects.get(username='existente'), colegio=self.colegio
        )
        r = self.client.post('/usuarios/ajax/crear/', {
            'tipo': 'colegio',
            'username': 'existente',
            'password': 'Clave789',
            'colegio_id': self.colegio.id,
        })
        data = r.json()
        self.assertFalse(data['ok'])

    def test_resetear_password_asigna_la_manual(self):
        user = User.objects.create_user(username='reset_test', password='antigua')
        perfil = UsuarioColegio.objects.create(user=user, colegio=self.colegio)
        r = self.client.post('/usuarios/ajax/resetear-password/', {
            'tipo': 'colegio',
            'perfil_id': perfil.id,
            'password': 'NuevaManual321',
        })
        data = r.json()
        self.assertTrue(data['ok'])
        user.refresh_from_db()
        self.assertTrue(user.check_password('NuevaManual321'))


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


# ── Panel del superusuario ────────────────────────────────────

class PanelAdminTest(TestCase):
    """Panel del apex: el superusuario aterriza aquí en vez de en el área."""

    def setUp(self):
        self.client = Client()  # host apex (testserver)
        User.objects.create_superuser(username='admin', password='adminpass')

    def test_seleccion_area_superusuario_redirige_al_panel(self):
        self.client.login(username='admin', password='adminpass')
        r = self.client.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/panel/', r['Location'])

    def test_panel_admin_superusuario_200(self):
        self.client.login(username='admin', password='adminpass')
        r = self.client.get('/panel/')
        self.assertEqual(r.status_code, 200)

    def test_panel_admin_no_superusuario_bloqueado(self):
        user = User.objects.create_user(username='pelao', password='pass')
        grupo, _ = Group.objects.get_or_create(name=GRUPO_STAFF_PROGRAMACION)
        user.groups.add(grupo)
        self.client.login(username='pelao', password='pass')
        r = self.client.get('/panel/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/usuarios/login/', r['Location'])

    def test_panel_lista_las_tres_areas_data_driven(self):
        """El contexto trae una sección por área (loop sobre GRUPOS_ETIQUETA)."""
        self.client.login(username='admin', password='adminpass')
        r = self.client.get('/panel/')
        secciones = r.context['usuarios_por_area']
        slugs = [s['slug'] for s in secciones]
        self.assertEqual(slugs, ['programacion', 'financiera', 'logistica'])

    def test_panel_muestra_estado_clave_pendiente(self):
        """Un empleado con debe_cambiar_password=True aparece como 'Clave pendiente'."""
        empleado = User.objects.create_user(username='emp_prog', password='x')
        grupo, _ = Group.objects.get_or_create(name=GRUPO_STAFF_PROGRAMACION)
        empleado.groups.add(grupo)
        PerfilEmpleado.objects.create(user=empleado, debe_cambiar_password=True)
        self.client.login(username='admin', password='adminpass')
        r = self.client.get('/panel/')
        self.assertContains(r, 'Clave pendiente')

    def test_panel_excluye_superusuario_metido_en_grupo(self):
        """Un superusuario dentro de un grupo de etiqueta NO se lista (no se gestiona aquí)."""
        otro_admin = User.objects.create_superuser(username='admin2', password='x')
        grupo, _ = Group.objects.get_or_create(name=GRUPO_STAFF_PROGRAMACION)
        otro_admin.groups.add(grupo)
        self.client.login(username='admin', password='adminpass')
        r = self.client.get('/panel/')
        seccion_prog = next(s for s in r.context['usuarios_por_area'] if s['slug'] == 'programacion')
        self.assertNotIn(otro_admin, list(seccion_prog['usuarios']))


# ── Usuarios de etiqueta (grupo area:programacion) ────────────

class UsuarioEtiquetaTest(TestCase):
    """Staff de área: acceso completo al área sin perfil; login los lleva a programación."""

    def setUp(self):
        self.area_client = Client(HTTP_HOST='programacion.testserver')
        self.apex_client = Client()
        self.grupo, _ = Group.objects.get_or_create(name=GRUPO_STAFF_PROGRAMACION)
        self.staff = User.objects.create_user(username='staff_prog', password='pass')
        self.staff.groups.add(self.grupo)

    def test_no_es_deslogueado_y_ve_el_home(self):
        """Antes caía en el logout del middleware por no tener perfil."""
        self.area_client.login(username='staff_prog', password='pass')
        r = self.area_client.get('/')
        self.assertEqual(r.status_code, 200)

    def test_accede_a_configuracion(self):
        self.area_client.login(username='staff_prog', password='pass')
        r = self.area_client.get('/configuracion/libros/')
        self.assertEqual(r.status_code, 200)

    def test_seleccion_area_lo_lleva_a_programacion(self):
        self.apex_client.login(username='staff_prog', password='pass')
        r = self.apex_client.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('programacion.testserver', r['Location'])

    def test_usuario_sin_etiqueta_sigue_bloqueado_en_configuracion(self):
        sin = User.objects.create_user(username='sin_rol', password='pass')
        # Sin perfil ni grupo → el middleware lo desloguea (sesión sin rol).
        self.area_client.login(username='sin_rol', password='pass')
        r = self.area_client.get('/configuracion/libros/')
        self.assertNotEqual(r.status_code, 200)


class AjaxUsuarioEtiquetaTest(TestCase):

    def setUp(self):
        self.client = Client()  # apex
        User.objects.create_superuser(username='admin', password='adminpass')
        self.client.login(username='admin', password='adminpass')
        self.grupo, _ = Group.objects.get_or_create(name=GRUPO_STAFF_PROGRAMACION)

    def test_crear_usuario_etiqueta_lo_mete_al_grupo(self):
        r = self.client.post('/usuarios/ajax/area/crear/', {
            'username': 'nuevo_prog', 'email': 'nuevo@ejemplo.com', 'password': 'Generica123',
        })
        data = r.json()
        self.assertTrue(data['ok'])
        self.assertNotIn('password_inicial', data)
        user = User.objects.get(username='nuevo_prog')
        self.assertTrue(user.groups.filter(name=GRUPO_STAFF_PROGRAMACION).exists())
        self.assertEqual(user.email, 'nuevo@ejemplo.com')
        self.assertTrue(user.check_password('Generica123'))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        # Debe cambiar la clave en el primer ingreso.
        self.assertTrue(user.perfil_empleado.debe_cambiar_password)

    def test_crear_usuario_etiqueta_sin_correo_falla(self):
        r = self.client.post('/usuarios/ajax/area/crear/', {
            'username': 'sin_correo', 'password': 'Generica123',
        })
        self.assertFalse(r.json()['ok'])
        self.assertFalse(User.objects.filter(username='sin_correo').exists())

    def test_crear_usuario_etiqueta_duplicado_falla(self):
        User.objects.create_user(username='ya_existe', password='x')
        r = self.client.post('/usuarios/ajax/area/crear/', {
            'username': 'ya_existe', 'email': 'x@ejemplo.com', 'password': 'Generica123',
        })
        self.assertFalse(r.json()['ok'])

    def test_resetear_password_etiqueta(self):
        user = User.objects.create_user(username='reset_prog', password='vieja')
        user.groups.add(self.grupo)
        PerfilEmpleado.objects.create(user=user, debe_cambiar_password=False)
        r = self.client.post('/usuarios/ajax/area/resetear/', {
            'user_id': user.id, 'password': 'NuevaGenerica999',
        })
        data = r.json()
        self.assertTrue(data['ok'])
        user.refresh_from_db()
        self.assertTrue(user.check_password('NuevaGenerica999'))
        # El reseteo vuelve a exigir el cambio.
        self.assertTrue(user.perfil_empleado.debe_cambiar_password)

    def test_editar_correo_etiqueta(self):
        user = User.objects.create_user(username='edita_prog', password='x', email='viejo@e.com')
        user.groups.add(self.grupo)
        r = self.client.post('/usuarios/ajax/area/editar/', {
            'user_id': user.id, 'email': 'nuevo@e.com',
        })
        self.assertTrue(r.json()['ok'])
        user.refresh_from_db()
        self.assertEqual(user.email, 'nuevo@e.com')

    def test_eliminar_usuario_etiqueta(self):
        user = User.objects.create_user(username='borrar_prog', password='x')
        user.groups.add(self.grupo)
        r = self.client.post('/usuarios/ajax/area/eliminar/', {'user_id': user.id})
        self.assertTrue(r.json()['ok'])
        self.assertFalse(User.objects.filter(username='borrar_prog').exists())

    def test_no_puede_resetear_a_un_no_etiqueta(self):
        otro = User.objects.create_user(username='otro', password='x')  # sin grupo
        r = self.client.post('/usuarios/ajax/area/resetear/', {'user_id': otro.id})
        self.assertFalse(r.json()['ok'])


class StaffGestionaUsuariosTest(TestCase):
    """El staff del área SÍ gestiona usuarios de colegio/profesor, pero NO los de etiqueta."""

    def setUp(self):
        self.area_client = Client(HTTP_HOST='programacion.testserver')
        self.grupo, _ = Group.objects.get_or_create(name=GRUPO_STAFF_PROGRAMACION)
        self.staff = User.objects.create_user(username='staff_prog', password='pass')
        self.staff.groups.add(self.grupo)
        self.colegio = Colegio.objects.create(nombre='Col Staff', ciudad='Bogotá')
        self.area_client.login(username='staff_prog', password='pass')

    def test_staff_accede_a_gestion_colegios(self):
        r = self.area_client.get('/usuarios/colegios/')
        self.assertEqual(r.status_code, 200)

    def test_staff_crea_usuario_de_colegio(self):
        r = self.area_client.post('/usuarios/ajax/crear/', {
            'tipo': 'colegio', 'username': 'col_por_staff',
            'password': 'ClaveStaff123', 'colegio_id': self.colegio.id,
        })
        self.assertTrue(r.json()['ok'])
        self.assertTrue(User.objects.filter(username='col_por_staff').exists())

    def test_staff_no_puede_crear_usuario_de_etiqueta(self):
        """El CRUD de etiqueta y el panel siguen siendo solo del superusuario."""
        r = self.area_client.post('/usuarios/ajax/area/crear/', {
            'username': 'intruso', 'email': 'x@e.com', 'password': 'Clave123',
        })
        self.assertEqual(r.status_code, 302)  # user_passes_test → login
        self.assertFalse(User.objects.filter(username='intruso').exists())


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

    def test_carrera_ttl_entre_add_e_incr_no_revienta(self):
        """Con Redis la clave puede expirar entre cache.add y cache.incr (dos
        round-trips de red): incr lanza ValueError. El decorador debe reponer el
        contador y atender la request, no propagar un 500 (visto en prod 2026-07-08)."""
        from unittest import mock
        from django.http import JsonResponse
        factory = RequestFactory()

        @rate_limit(max_calls=2, periodo=60)
        def vista_test(request):
            return JsonResponse({'ok': True})

        incr_real = cache.incr
        estado = {'primera': True}

        def incr_con_expiracion(key, *args, **kwargs):
            if estado['primera']:
                estado['primera'] = False
                cache.delete(key)  # simula el TTL venciendo justo tras el add
                raise ValueError(f"Key '{key}' not found")
            return incr_real(key, *args, **kwargs)

        request = factory.get('/')
        request.META['REMOTE_ADDR'] = '10.7.7.7'
        with mock.patch.object(cache, 'incr', side_effect=incr_con_expiracion):
            r = vista_test(request)
        self.assertEqual(r.status_code, 200)

        # El contador quedó bien repuesto: el límite sigue aplicando después.
        request = factory.get('/')
        request.META['REMOTE_ADDR'] = '10.7.7.7'
        self.assertEqual(vista_test(request).status_code, 200)
        request = factory.get('/')
        request.META['REMOTE_ADDR'] = '10.7.7.7'
        self.assertEqual(vista_test(request).status_code, 429)

    def test_proxy_cgnat_railway_usa_xff(self):
        """El proxy de Railway llega desde 100.64.0.0/10 (CGNAT, no 'privado' para
        ipaddress): debe tomarse el XFF para que cada cliente tenga su propio contador
        y no compartan todos el límite bajo la IP del proxy."""
        factory = RequestFactory()

        @rate_limit(max_calls=2, periodo=60)
        def vista_test(request):
            from django.http import JsonResponse
            return JsonResponse({'ok': True})

        def peticion(ip_cliente):
            request = factory.get('/')
            request.META['REMOTE_ADDR'] = '100.64.0.4'
            request.META['HTTP_X_FORWARDED_FOR'] = ip_cliente
            return vista_test(request)

        # El cliente A agota su límite…
        for _ in range(2):
            self.assertEqual(peticion('203.0.113.10').status_code, 200)
        self.assertEqual(peticion('203.0.113.10').status_code, 429)

        # …pero el cliente B no se ve afectado (contadores independientes).
        self.assertEqual(peticion('203.0.113.20').status_code, 200)

    def test_cdn_railway_toma_primer_xff(self):
        """Vía la capa CDN de Railway el XFF llega como 'cliente, pop_cdn': debe usarse
        el PRIMER valor (el cliente real); con el último todos los usuarios detrás del
        mismo POP regional compartirían contador."""
        factory = RequestFactory()

        @rate_limit(max_calls=2, periodo=60)
        def vista_test(request):
            from django.http import JsonResponse
            return JsonResponse({'ok': True})

        def peticion(ip_cliente):
            request = factory.get('/')
            request.META['REMOTE_ADDR'] = '100.64.0.4'
            # mismo POP del CDN al final para ambos clientes
            request.META['HTTP_X_FORWARDED_FOR'] = f'{ip_cliente}, 84.17.44.225'
            return vista_test(request)

        for _ in range(2):
            self.assertEqual(peticion('203.0.113.10').status_code, 200)
        self.assertEqual(peticion('203.0.113.10').status_code, 429)
        # Cliente distinto detrás del MISMO POP: contador propio.
        self.assertEqual(peticion('203.0.113.20').status_code, 200)

    def test_xff_invalido_cae_a_remote_addr(self):
        """Un primer valor de XFF que no parsea como IP no debe romper la vista ni
        usarse como llave: se cae a REMOTE_ADDR."""
        factory = RequestFactory()

        @rate_limit(max_calls=2, periodo=60)
        def vista_test(request):
            from django.http import JsonResponse
            return JsonResponse({'ok': True})

        request = factory.get('/')
        request.META['REMOTE_ADDR'] = '100.64.0.4'
        request.META['HTTP_X_FORWARDED_FOR'] = 'no-soy-una-ip, 84.17.44.225'
        self.assertEqual(vista_test(request).status_code, 200)

    def test_cloudflare_usa_cf_connecting_ip(self):
        """miltonochoa.app está proxied por Cloudflare: el primer XFF es el nodo CF
        (Railway lo pone), y la IP real del usuario viaja en CF-Connecting-IP. Dos
        usuarios detrás del MISMO nodo CF deben tener contadores independientes."""
        factory = RequestFactory()

        @rate_limit(max_calls=2, periodo=60)
        def vista_test(request):
            from django.http import JsonResponse
            return JsonResponse({'ok': True})

        def peticion(ip_usuario):
            request = factory.get('/')
            request.META['REMOTE_ADDR'] = '100.64.0.4'
            # 172.68.12.53 ∈ 172.64.0.0/13 (rango publicado de Cloudflare)
            request.META['HTTP_X_FORWARDED_FOR'] = '172.68.12.53, 84.17.44.225'
            request.META['HTTP_CF_CONNECTING_IP'] = ip_usuario
            return vista_test(request)

        for _ in range(2):
            self.assertEqual(peticion('203.0.113.10').status_code, 200)
        self.assertEqual(peticion('203.0.113.10').status_code, 429)
        self.assertEqual(peticion('203.0.113.20').status_code, 200)

    def test_cf_connecting_ip_falso_sin_cloudflare_se_ignora(self):
        """Quien llega DIRECTO a Railway (primer XFF = su IP real, no un nodo CF) no
        puede evadir el límite rotando un CF-Connecting-IP inventado."""
        factory = RequestFactory()

        @rate_limit(max_calls=2, periodo=60)
        def vista_test(request):
            from django.http import JsonResponse
            return JsonResponse({'ok': True})

        def peticion(cf_falso):
            request = factory.get('/')
            request.META['REMOTE_ADDR'] = '100.64.0.4'
            request.META['HTTP_X_FORWARDED_FOR'] = '203.0.113.66, 84.17.44.225'
            request.META['HTTP_CF_CONNECTING_IP'] = cf_falso
            return vista_test(request)

        # Rota el header falso en cada request: igual lo cuenta su IP real → 429.
        self.assertEqual(peticion('9.9.9.1').status_code, 200)
        self.assertEqual(peticion('9.9.9.2').status_code, 200)
        self.assertEqual(peticion('9.9.9.3').status_code, 429)


# ── Telemetría: capturador de errores del navegador ───────────
class TelemetriaErrorClienteTest(TestCase):

    def setUp(self):
        # Host de área: el endpoint debe ser accesible aunque el middleware de acceso
        # restrinja a colegio/profesor (va en RUTAS_PUBLICAS).
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.url = '/usuarios/telemetria/error/'

    def test_post_valido_crea_registro(self):
        payload = {
            'tipo': 'fetch',
            'mensaje': 'Fallo de red en POST /colegios/ajax/guardar/',
            'stack': 'TypeError: failed to fetch',
            'url': 'https://programacion.testserver/colegios/',
            'breadcrumbs': [{'t': '2026-06-04T17:00:00Z', 'tipo': 'click', 'detalle': 'button «Guardar»'}],
        }
        r = self.client.post(self.url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ErrorCliente.objects.count(), 1)
        e = ErrorCliente.objects.first()
        self.assertEqual(e.tipo, 'fetch')
        self.assertEqual(len(e.breadcrumbs), 1)

    def test_usuario_anonimo_se_registra_sin_user(self):
        # Sin sesión: el reporte igual se guarda (usuario=None), no se pierde el error.
        r = self.client.post(self.url, data=json.dumps({'tipo': 'error', 'mensaje': 'x'}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(ErrorCliente.objects.first().usuario)

    def test_json_invalido_no_revienta(self):
        # Tolerante: cuerpo basura → 400 controlado, nunca un 500.
        r = self.client.post(self.url, data='no-es-json{', content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(ErrorCliente.objects.count(), 0)

    def test_get_no_permitido(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)


# ── Endurecimiento de seguridad (telemetría, logins, claves) ──

class TelemetriaAbuseTest(TestCase):
    """El endpoint es público y anónimo (RUTAS_PUBLICAS): sin rate limit ni topes de
    tamaño, cualquiera podría llenar la BD con megabytes por request."""

    def setUp(self):
        cache.clear()
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.url = '/usuarios/telemetria/error/'

    def tearDown(self):
        cache.clear()

    def _post(self, payload):
        return self.client.post(self.url, data=json.dumps(payload),
                                content_type='application/json')

    def test_rate_limit_corta_la_rafaga(self):
        for _ in range(20):
            self.assertEqual(self._post({'tipo': 'error', 'mensaje': 'x'}).status_code, 200)
        r = self._post({'tipo': 'error', 'mensaje': 'x'})
        self.assertEqual(r.status_code, 429)
        self.assertEqual(ErrorCliente.objects.count(), 20)  # el 21º no se guardó

    def test_extra_gigante_se_descarta_pero_el_error_se_guarda(self):
        r = self._post({'tipo': 'error', 'mensaje': 'real',
                        'extra': {'relleno': 'A' * 50000}})
        self.assertEqual(r.status_code, 200)
        e = ErrorCliente.objects.first()
        self.assertEqual(e.mensaje, 'real')   # el reporte no se pierde
        self.assertEqual(e.extra, {})         # el campo inflado sí

    def test_breadcrumbs_gigantes_se_descartan(self):
        crumbs = [{'t': 'x', 'tipo': 'click', 'detalle': 'B' * 5000} for _ in range(10)]
        r = self._post({'tipo': 'error', 'mensaje': 'real', 'breadcrumbs': crumbs})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ErrorCliente.objects.first().breadcrumbs, [])

    def test_extra_normal_sigue_pasando(self):
        r = self._post({'tipo': 'fetch', 'mensaje': 'x', 'extra': {'status': 502, 'ms': 1200}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ErrorCliente.objects.first().extra, {'status': 502, 'ms': 1200})


class LoginRateLimitTest(TestCase):
    """vista_login responde 429 en HTML (es un form de navegador, no AJAX) y el login
    de /admin/ (form propio de Django) también queda rate-limited."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_login_429_es_html(self):
        for _ in range(10):
            self.client.post('/usuarios/login/', {'username': 'nadie', 'password': 'mala'})
        r = self.client.post('/usuarios/login/', {'username': 'nadie', 'password': 'mala'})
        self.assertEqual(r.status_code, 429)
        self.assertIn('text/html', r['Content-Type'])

    def test_admin_login_tiene_rate_limit(self):
        for _ in range(10):
            self.client.get('/admin/login/')
        r = self.client.get('/admin/login/')
        self.assertEqual(r.status_code, 429)


class PasswordTemporalMinimaTest(TestCase):
    """El staff asigna la clave a mano, pero el login es público en internet:
    se exige un mínimo de 8 caracteres (sin el resto de validadores de Django)."""

    def setUp(self):
        cache.clear()
        User.objects.create_superuser(username='admin', password='adminpass')
        self.client.login(username='admin', password='adminpass')
        self.colegio = Colegio.objects.create(nombre='Colegio Min', ciudad='Bogotá')

    def test_crear_usuario_con_clave_corta_falla(self):
        r = self.client.post('/usuarios/ajax/crear/', {
            'tipo': 'colegio', 'username': 'col_corto',
            'password': 'corta12',  # 7 caracteres
            'colegio_id': self.colegio.id,
        })
        self.assertEqual(r.status_code, 400)
        self.assertIn('8 caracteres', r.json()['error'])
        self.assertFalse(User.objects.filter(username='col_corto').exists())

    def test_crear_usuario_con_clave_de_8_pasa(self):
        r = self.client.post('/usuarios/ajax/crear/', {
            'tipo': 'colegio', 'username': 'col_ok',
            'password': 'clave123',  # 8 justos
            'colegio_id': self.colegio.id,
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(User.objects.filter(username='col_ok').exists())
