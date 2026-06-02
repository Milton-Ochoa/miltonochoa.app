"""
Tests — app: informes
Modelo: Informe
Vistas: obtener_informe, guardar_informe, lista_informes, eliminar_informe, detalle_informe
"""
import json
from django.test import TestCase, Client
from django.contrib.auth.models import User
from datetime import date
from datetime import time as dt_time
from programacion.configuracion.models import Colegio, ColegioAnio, Profesor, Materia
from programacion.colegios.models import Bloque, Clase, ClaseParticular, Grado
from programacion.informes.models import Informe
from usuarios.models import UsuarioColegio, UsuarioProfesor


# ── Helpers reutilizables ─────────────────────────────────────

def crear_clase(colegio, profesor, fecha=None):
    grado_obj, _ = Grado.objects.get_or_create(nombre='11-1')
    materia_obj, _ = Materia.objects.get_or_create(nombre='Lectura Crítica')
    bloque = Bloque.objects.create(
        colegio=colegio, grado=grado_obj,
        hora_inicio=dt_time(8, 0), hora_fin=dt_time(10, 0)
    )
    return Clase.objects.create(
        colegio=colegio, bloque=bloque,
        fecha=fecha or date.today(),
        profesor=profesor, materia=materia_obj, unidad='1',
    )


def crear_informe(profesor, clase, actividades=''):
    return Informe.objects.create(
        profesor=profesor, clase=clase,
        colegio_nombre=clase.colegio.nombre,
        grado='11-1', fecha=clase.fecha,
        materia='Lectura Crítica', tematica='Unidad 1',
        material='Saberes 11 Oro', actividades=actividades,
    )


# ── Modelo ────────────────────────────────────────────────────

class InformeModelTest(TestCase):

    def setUp(self):
        self.profesor = Profesor.objects.create(nombre='Ana', apellido='García')
        col = Colegio.objects.create(nombre='Col Test', departamento='Santander', ciudad='BGA')
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)
        self.clase = crear_clase(self.colegio, self.profesor)

    def test_completado_true_si_tiene_actividades(self):
        inf = crear_informe(self.profesor, self.clase, actividades='Lectura en clase.')
        self.assertTrue(inf.completado)

    def test_completado_false_si_actividades_vacias(self):
        inf = crear_informe(self.profesor, self.clase, actividades='')
        self.assertFalse(inf.completado)

    def test_completado_false_si_actividades_solo_espacios(self):
        inf = crear_informe(self.profesor, self.clase, actividades='   ')
        self.assertFalse(inf.completado)

    def test_str_incluye_fecha_y_colegio(self):
        inf = crear_informe(self.profesor, self.clase)
        self.assertIn('Col Test', str(inf))

    def test_one_to_one_con_clase(self):
        inf = crear_informe(self.profesor, self.clase)
        self.assertEqual(self.clase.informe, inf)

    def test_no_se_pueden_crear_dos_informes_para_la_misma_clase(self):
        from django.db import IntegrityError
        crear_informe(self.profesor, self.clase)
        with self.assertRaises(IntegrityError):
            Informe.objects.create(
                profesor=self.profesor, clase=self.clase,
                colegio_nombre='Col Test', grado='11-1',
                fecha=date.today(), materia='LC',
                tematica='U1', material='Libro A',
            )

    def test_campos_texto_tienen_default_vacio(self):
        inf = Informe.objects.create(
            profesor=self.profesor, clase=self.clase,
            colegio_nombre='Col Test', grado='11-1',
            fecha=date.today(), materia='LC',
            tematica='U1', material='Libro A',
        )
        self.assertEqual(inf.actividades, '')
        self.assertEqual(inf.fortalezas, '')
        self.assertEqual(inf.debilidades, '')


# ── Vista AJAX: obtener_informe ───────────────────────────────

class ObtenerInformeTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        User.objects.create_superuser(username='admin', password='pass')
        self.client.login(username='admin', password='pass')
        self.profesor = Profesor.objects.create(nombre='Luis', apellido='Martínez')
        col = Colegio.objects.create(nombre='Col AJAX', departamento='Santander', ciudad='BGA')
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)
        self.clase = crear_clase(self.colegio, self.profesor)

    def test_clase_sin_informe_devuelve_existe_false(self):
        r = self.client.get(f'/informes/ajax/obtener/?clase_id={self.clase.id}')
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertFalse(data['existe'])

    def test_clase_con_informe_devuelve_datos(self):
        crear_informe(self.profesor, self.clase, actividades='Ejercicios.')
        r = self.client.get(f'/informes/ajax/obtener/?clase_id={self.clase.id}')
        data = json.loads(r.content)
        self.assertTrue(data['existe'])
        self.assertEqual(data['actividades'], 'Ejercicios.')
        self.assertEqual(data['colegio_nombre'], 'Col AJAX')

    def test_sin_parametros_devuelve_existe_false(self):
        r = self.client.get('/informes/ajax/obtener/')
        data = json.loads(r.content)
        self.assertFalse(data['existe'])

    def test_no_autenticado_redirige(self):
        self.client.logout()
        r = self.client.get(f'/informes/ajax/obtener/?clase_id={self.clase.id}')
        self.assertEqual(r.status_code, 302)


# ── Vista AJAX: guardar_informe ───────────────────────────────

class GuardarInformeTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        User.objects.create_superuser(username='admin', password='pass')
        self.client.login(username='admin', password='pass')
        self.profesor = Profesor.objects.create(nombre='María', apellido='Torres')
        col = Colegio.objects.create(nombre='Col Guardar', departamento='Valle', ciudad='Cali')
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)
        self.clase = crear_clase(self.colegio, self.profesor)

    def _payload(self, clase_id=None, particular_id=None, actividades='Texto.'):
        return {
            'clase_id':      clase_id,
            'particular_id': particular_id,
            'profesor_id':   self.profesor.id,
            'fecha_iso':     str(date.today()),
            'colegio_nombre': self.colegio.nombre,
            'grado':         '11-1',
            'materia':       'Lectura Crítica',
            'tematica':      'Unidad 1',
            'material':      'Saberes 11 Oro',
            'actividades':   actividades,
            'fortalezas':    '',
            'debilidades':   '',
            'recomendaciones': '',
            'bibliografia':  '',
        }

    def test_crea_informe_correctamente(self):
        r = self.client.post(
            '/informes/ajax/guardar/',
            data=json.dumps(self._payload(clase_id=self.clase.id)),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertTrue(data['ok'])
        self.assertTrue(Informe.objects.filter(clase=self.clase).exists())

    def test_actualiza_informe_existente(self):
        crear_informe(self.profesor, self.clase, actividades='Texto original.')
        r = self.client.post(
            '/informes/ajax/guardar/',
            data=json.dumps(self._payload(clase_id=self.clase.id, actividades='Texto actualizado.')),
            content_type='application/json',
        )
        data = json.loads(r.content)
        self.assertTrue(data['ok'])
        # Solo debe existir un informe — no se duplicó
        self.assertEqual(Informe.objects.filter(clase=self.clase).count(), 1)
        self.assertEqual(Informe.objects.get(clase=self.clase).actividades, 'Texto actualizado.')

    def test_sin_clase_ni_particular_devuelve_error(self):
        r = self.client.post(
            '/informes/ajax/guardar/',
            data=json.dumps(self._payload()),  # clase_id=None, particular_id=None
            content_type='application/json',
        )
        data = json.loads(r.content)
        self.assertFalse(data['ok'])

    def test_json_invalido_devuelve_400(self):
        r = self.client.post(
            '/informes/ajax/guardar/',
            data='esto no es json',
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 400)

    def test_get_no_permitido(self):
        r = self.client.get('/informes/ajax/guardar/')
        self.assertEqual(r.status_code, 405)  # Method Not Allowed


# ── Vista: lista_informes ─────────────────────────────────────

class ListaInformesTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.admin = User.objects.create_superuser(username='admin', password='pass')
        self.profesor = Profesor.objects.create(nombre='Jorge', apellido='Pérez')
        col = Colegio.objects.create(nombre='Col Lista', departamento='Santander', ciudad='BGA')
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)
        self.clase = crear_clase(self.colegio, self.profesor)
        crear_informe(self.profesor, self.clase, actividades='Algo.')

    def test_admin_puede_ver_todos_los_informes(self):
        self.client.login(username='admin', password='pass')
        r = self.client.get('/informes/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['informes'].count(), 1)

    def test_filtro_por_colegio(self):
        self.client.login(username='admin', password='pass')
        r = self.client.get('/informes/?colegio=Col Lista')
        self.assertEqual(r.context['informes'].count(), 1)

    def test_filtro_colegio_que_no_existe_devuelve_cero(self):
        self.client.login(username='admin', password='pass')
        r = self.client.get('/informes/?colegio=Inexistente')
        self.assertEqual(r.context['informes'].count(), 0)

    def test_filtro_solo_completos(self):
        self.client.login(username='admin', password='pass')
        r = self.client.get('/informes/?completos=1')
        # El informe de setUp tiene actividades → aparece
        self.assertEqual(r.context['informes'].count(), 1)

    def test_usuario_profesor_solo_ve_sus_informes(self):
        user = User.objects.create_user(username='jorge', password='pass')
        UsuarioProfesor.objects.create(
            user=user, profesor=self.profesor
        )
        otro_profesor = Profesor.objects.create(nombre='Otro', apellido='Prof')
        otro_col = Colegio.objects.create(nombre='Col Otro', departamento='Santander', ciudad='BGA')
        otro_colegio = ColegioAnio.objects.create(colegio=otro_col, anio=2026, activo=True)
        otra_clase = crear_clase(otro_colegio, otro_profesor)
        crear_informe(otro_profesor, otra_clase, actividades='Otro texto.')

        self.client.login(username='jorge', password='pass')
        r = self.client.get('/informes/')
        self.assertEqual(r.status_code, 200)
        # Solo debe ver su propio informe, no el del otro profesor
        for inf in r.context['informes']:
            self.assertEqual(inf.profesor, self.profesor)

    def test_usuario_colegio_solo_ve_informes_de_su_colegio(self):
        user = User.objects.create_user(username='user_col', password='pass')
        UsuarioColegio.objects.create(
            user=user, colegio=self.colegio.colegio
        )
        self.client.login(username='user_col', password='pass')
        r = self.client.get('/informes/')
        self.assertEqual(r.status_code, 200)
        for inf in r.context['informes']:
            self.assertEqual(inf.colegio_nombre, self.colegio.nombre)


# ── Acceso por perfil a lista de informes ────────────────────

class ListaInformesAccesoTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.admin = User.objects.create_superuser('admin_inf', password='pass')
        col = Colegio.objects.create(
            nombre='Col Inf', departamento='Santander', ciudad='BGA'
        )
        self.colegio = col
        self.profesor = Profesor.objects.create(nombre='Ana', apellido='López')
        user_col  = User.objects.create_user('user_col_inf', password='pass')
        user_prof = User.objects.create_user('user_prof_inf', password='pass')
        UsuarioColegio.objects.create(user=user_col, colegio=self.colegio)
        UsuarioProfesor.objects.create(user=user_prof, profesor=self.profesor)
        Informe.objects.create(
            profesor=self.profesor, colegio_nombre='Col Inf',
            grado='11-1', fecha=date.today(),
            materia='Matemáticas', tematica='Álgebra', material='Libro X',
        )
        Informe.objects.create(
            profesor=self.profesor, colegio_nombre='Otro Colegio',
            grado='10-1', fecha=date.today(),
            materia='Física', tematica='Mecánica', material='Libro Y',
        )

    def test_admin_ve_todos_los_informes(self):
        self.client.login(username='admin_inf', password='pass')
        r = self.client.get('/informes/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['informes'].paginator.count, 2)

    def test_usuario_colegio_solo_ve_sus_informes(self):
        self.client.login(username='user_col_inf', password='pass')
        r = self.client.get('/informes/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['informes'].paginator.count, 1)

    def test_usuario_profesor_solo_ve_sus_informes(self):
        self.client.login(username='user_prof_inf', password='pass')
        r = self.client.get('/informes/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['informes'].paginator.count, 2)


# ── Vista: eliminar_informe ───────────────────────────────────

class EliminarInformeTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.admin = User.objects.create_superuser(username='admin', password='pass')
        self.profesor = Profesor.objects.create(nombre='Test', apellido='Prof')
        col = Colegio.objects.create(nombre='Col Elim', departamento='Santander', ciudad='BGA')
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)
        self.clase = crear_clase(self.colegio, self.profesor)
        self.informe = crear_informe(self.profesor, self.clase, actividades='X.')

    def test_superusuario_puede_eliminar(self):
        self.client.login(username='admin', password='pass')
        r = self.client.post(f'/informes/{self.informe.id}/eliminar/')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Informe.objects.filter(id=self.informe.id).exists())

    def test_usuario_normal_no_puede_eliminar(self):
        user = User.objects.create_user(username='normal', password='pass')
        UsuarioProfesor.objects.create(
            user=user, profesor=self.profesor
        )
        self.client.login(username='normal', password='pass')
        r = self.client.post(f'/informes/{self.informe.id}/eliminar/')
        # Debe devolver 403 Forbidden
        self.assertEqual(r.status_code, 403)
        # El informe sigue existiendo
        self.assertTrue(Informe.objects.filter(id=self.informe.id).exists())

    def test_informe_inexistente_devuelve_404(self):
        self.client.login(username='admin', password='pass')
        r = self.client.post('/informes/99999/eliminar/')
        self.assertEqual(r.status_code, 404)