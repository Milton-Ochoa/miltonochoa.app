"""
Tests — app: usuarios (gestión de usuarios)
Vistas: panel_admin, gestionar_usuarios, ajax_crear_usuario, ajax_resetear_password
y el CRUD de usuarios de etiqueta del apex.
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User, Group
from programacion.configuracion.models import Colegio, Profesor
from usuarios.models import UsuarioColegio, UsuarioProfesor, PerfilEmpleado
from core.areas import GRUPO_STAFF_PROGRAMACION


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


# ── Inhabilitar / habilitar (no existe el borrado) ────────────

class AjaxActivarUsuarioTest(TestCase):
    """Usuarios de colegio/profesor: se inhabilitan, no se borran (la auditoría cuelga
    de FKs SET_NULL, así que borrar el User destruiría el rastro)."""

    def setUp(self):
        self.client = Client()
        User.objects.create_superuser(username='admin', password='adminpass')
        self.client.login(username='admin', password='adminpass')
        self.colegio = Colegio.objects.create(nombre='Col Act', ciudad='Bogotá')
        self.profesor = Profesor.objects.create(nombre='Luis', apellido='Ruiz')
        self.user_col = User.objects.create_user(username='col_act', password='x')
        self.perfil_col = UsuarioColegio.objects.create(user=self.user_col, colegio=self.colegio)
        self.user_prof = User.objects.create_user(username='prof_act', password='x')
        self.perfil_prof = UsuarioProfesor.objects.create(user=self.user_prof, profesor=self.profesor)

    def _post(self, tipo, perfil_id, activo):
        return self.client.post('/usuarios/ajax/activar/', {
            'tipo': tipo, 'perfil_id': perfil_id, 'activo': activo,
        })

    def test_inhabilitar_y_habilitar_usuario_colegio(self):
        r = self._post('colegio', self.perfil_col.id, '0')
        self.assertTrue(r.json()['ok'])
        self.user_col.refresh_from_db()
        self.assertFalse(self.user_col.is_active)
        # Ni el User ni el perfil se borran: el vínculo con el colegio sigue intacto.
        self.assertTrue(UsuarioColegio.objects.filter(id=self.perfil_col.id).exists())

        self._post('colegio', self.perfil_col.id, '1')
        self.user_col.refresh_from_db()
        self.assertTrue(self.user_col.is_active)

    def test_inhabilitar_y_habilitar_usuario_profesor(self):
        r = self._post('profesor', self.perfil_prof.id, '0')
        self.assertTrue(r.json()['ok'])
        self.user_prof.refresh_from_db()
        self.assertFalse(self.user_prof.is_active)
        self.assertTrue(UsuarioProfesor.objects.filter(id=self.perfil_prof.id).exists())

        self._post('profesor', self.perfil_prof.id, '1')
        self.user_prof.refresh_from_db()
        self.assertTrue(self.user_prof.is_active)

    def test_estado_invalido_es_rechazado(self):
        r = self._post('colegio', self.perfil_col.id, 'quizas')
        self.assertEqual(r.status_code, 400)
        self.user_col.refresh_from_db()
        self.assertTrue(self.user_col.is_active)

    def test_usuario_sin_permisos_no_puede_activar(self):
        pelao = User.objects.create_user(username='pelao_act', password='pass')
        cliente = Client()
        cliente.login(username='pelao_act', password='pass')
        r = cliente.post('/usuarios/ajax/activar/', {
            'tipo': 'colegio', 'perfil_id': self.perfil_col.id, 'activo': '0',
        })
        self.assertEqual(r.status_code, 302)  # user_passes_test → login
        self.user_col.refresh_from_db()
        self.assertTrue(self.user_col.is_active)


class BorradoDeUsuariosNoExisteTest(TestCase):
    """El borrado de usuarios se retiró de la app por completo (queda solo en /admin/)."""

    def setUp(self):
        self.client = Client()
        User.objects.create_superuser(username='admin', password='adminpass')
        self.client.login(username='admin', password='adminpass')

    def test_no_hay_url_de_eliminar(self):
        from django.urls import NoReverseMatch, reverse
        for nombre in ('ajax_eliminar_usuario', 'ajax_eliminar_usuario_area'):
            with self.assertRaises(NoReverseMatch):
                reverse(nombre)

    def test_las_rutas_de_eliminar_responden_404(self):
        for ruta in ('/usuarios/ajax/eliminar/', '/usuarios/ajax/area/eliminar/'):
            self.assertEqual(self.client.post(ruta).status_code, 404)


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

    def test_panel_marca_los_inhabilitados(self):
        """El inhabilitado se sigue listando (para poder rehabilitarlo) pero con la marca
        que el checkbox 'Ver usuarios inhabilitados' usa para mostrarlo."""
        emp = User.objects.create_user(username='emp_off', password='x', is_active=False)
        grupo, _ = Group.objects.get_or_create(name=GRUPO_STAFF_PROGRAMACION)
        emp.groups.add(grupo)
        self.client.login(username='admin', password='adminpass')
        r = self.client.get('/panel/')
        self.assertContains(r, 'data-inactivo="1"')
        self.assertContains(r, 'Inhabilitado')

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

    def test_inhabilitar_y_habilitar_usuario_etiqueta(self):
        """Inhabilitar NO borra el User: se puede revertir (el borrado ya no existe)."""
        user = User.objects.create_user(username='inhab_prog', password='x')
        user.groups.add(self.grupo)

        r = self.client.post('/usuarios/ajax/area/activar/', {'user_id': user.id, 'activo': '0'})
        data = r.json()
        self.assertTrue(data['ok'])
        self.assertFalse(data['activo'])
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertTrue(User.objects.filter(username='inhab_prog').exists())

        r = self.client.post('/usuarios/ajax/area/activar/', {'user_id': user.id, 'activo': '1'})
        self.assertTrue(r.json()['activo'])
        user.refresh_from_db()
        self.assertTrue(user.is_active)

    def test_activar_usuario_etiqueta_sin_estado_falla(self):
        user = User.objects.create_user(username='sin_estado', password='x')
        user.groups.add(self.grupo)
        r = self.client.post('/usuarios/ajax/area/activar/', {'user_id': user.id})
        self.assertFalse(r.json()['ok'])
        user.refresh_from_db()
        self.assertTrue(user.is_active)

    def test_no_puede_inhabilitar_a_un_no_etiqueta(self):
        otro = User.objects.create_user(username='otro_no_etiqueta', password='x')  # sin grupo
        r = self.client.post('/usuarios/ajax/area/activar/', {'user_id': otro.id, 'activo': '0'})
        self.assertFalse(r.json()['ok'])
        otro.refresh_from_db()
        self.assertTrue(otro.is_active)

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

    def test_staff_inhabilita_usuario_de_colegio(self):
        user = User.objects.create_user(username='col_del_staff', password='x')
        perfil = UsuarioColegio.objects.create(user=user, colegio=self.colegio)
        r = self.area_client.post('/usuarios/ajax/activar/', {
            'tipo': 'colegio', 'perfil_id': perfil.id, 'activo': '0',
        })
        self.assertTrue(r.json()['ok'])
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_staff_no_puede_inhabilitar_usuario_de_etiqueta(self):
        otro = User.objects.create_user(username='otro_staff', password='x')
        otro.groups.add(self.grupo)
        r = self.area_client.post('/usuarios/ajax/area/activar/', {
            'user_id': otro.id, 'activo': '0',
        })
        self.assertEqual(r.status_code, 302)  # solo_admin → login
        otro.refresh_from_db()
        self.assertTrue(otro.is_active)
