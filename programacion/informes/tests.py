"""
Tests — app: informes
Modelo: Informe
Vistas: obtener_informe, guardar_informe, lista_informes, eliminar_informe, detalle_informe
"""
import json
from unittest.mock import patch
from django.core.cache import cache
from django.test import TestCase, Client
from django.contrib.auth.models import User
from datetime import date, datetime, timedelta
from datetime import time as dt_time
from programacion.configuracion.models import Colegio, ColegioAnio, Profesor, Materia
from programacion.colegios.models import Bloque, Clase, ClasePersonalizada, Grado
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

    def test_profesor_no_puede_leer_informe_ajeno(self):
        # Regresión: obtener_informe debe aplicar el mismo scoping que detalle_informe.
        crear_informe(self.profesor, self.clase, actividades='Privado.')
        otro = Profesor.objects.create(nombre='Otro', apellido='Prof')
        user = User.objects.create_user(username='otro_prof', password='pass')
        UsuarioProfesor.objects.create(user=user, profesor=otro)
        self.client.login(username='otro_prof', password='pass')
        r = self.client.get(f'/informes/ajax/obtener/?clase_id={self.clase.id}')
        self.assertEqual(r.status_code, 403)

    def test_profesor_si_puede_leer_su_propio_informe(self):
        crear_informe(self.profesor, self.clase, actividades='Mío.')
        user = User.objects.create_user(username='luis_prof', password='pass')
        UsuarioProfesor.objects.create(user=user, profesor=self.profesor)
        self.client.login(username='luis_prof', password='pass')
        r = self.client.get(f'/informes/ajax/obtener/?clase_id={self.clase.id}')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(json.loads(r.content)['existe'])


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

    def _payload(self, clase_id=None, personalizada_id=None, actividades='Texto.'):
        return {
            'clase_id':      clase_id,
            'personalizada_id': personalizada_id,
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

    def test_sin_clase_ni_personalizada_devuelve_error(self):
        r = self.client.post(
            '/informes/ajax/guardar/',
            data=json.dumps(self._payload()),  # clase_id=None, personalizada_id=None
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

    def test_perfil_profesor_ignora_profesor_id_del_body(self):
        # Blindaje de identidad: aunque el body traiga el id de otro profesor
        # (p. ej. manipulando el payload del modal de la lista), el informe se
        # guarda bajo el profesor del perfil autenticado.
        user = User.objects.create_user(username='prof_blindaje', password='pass')
        UsuarioProfesor.objects.create(user=user, profesor=self.profesor)
        otro = Profesor.objects.create(nombre='Suplantado', apellido='Ajeno')
        self.client.login(username='prof_blindaje', password='pass')

        payload = self._payload(clase_id=self.clase.id)
        payload['profesor_id'] = otro.id
        r = self.client.post(
            '/informes/ajax/guardar/',
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertTrue(json.loads(r.content)['ok'])
        self.assertEqual(
            Informe.objects.get(clase=self.clase).profesor_id, self.profesor.id
        )


# ── Vista: lista_informes ─────────────────────────────────────

class ListaInformesTest(TestCase):
    """La vista entrega TODO el dataset como dicts en `filas` (el filtrado fino
    es responsabilidad del JS del template)."""

    def setUp(self):
        cache.clear()  # la lista se cachea por user id; evita fugas entre tests
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
        self.assertEqual(len(r.context['filas']), 1)
        self.assertEqual(r.context['filas'][0]['colegio_nombre'], 'Col Lista')

    def test_clase_pasada_sin_informe_aparece_como_pendiente(self):
        ayer = date.today() - timedelta(days=1)
        crear_clase(self.colegio, self.profesor, fecha=ayer)
        self.client.login(username='admin', password='pass')
        r = self.client.get('/informes/')
        pendientes = [f for f in r.context['filas'] if f['informe_id'] is None]
        self.assertEqual(len(pendientes), 1)
        self.assertFalse(pendientes[0]['completado'])

    def test_usuario_profesor_solo_ve_sus_informes(self):
        user = User.objects.create_user(username='jorge', password='pass')
        UsuarioProfesor.objects.create(user=user, profesor=self.profesor)
        otro_profesor = Profesor.objects.create(nombre='Otro', apellido='Prof')
        otro_col = Colegio.objects.create(nombre='Col Otro', departamento='Santander', ciudad='BGA')
        otro_colegio = ColegioAnio.objects.create(colegio=otro_col, anio=2026, activo=True)
        otra_clase = crear_clase(otro_colegio, otro_profesor)
        crear_informe(otro_profesor, otra_clase, actividades='Otro texto.')

        self.client.login(username='jorge', password='pass')
        r = self.client.get('/informes/')
        self.assertEqual(r.status_code, 200)
        # Solo debe ver su propio informe, no el del otro profesor
        self.assertEqual(len(r.context['filas']), 1)
        self.assertEqual(r.context['filas'][0]['profesor'], 'Jorge Pérez')

    def test_usuario_colegio_solo_ve_informes_de_su_colegio(self):
        user = User.objects.create_user(username='user_col', password='pass')
        UsuarioColegio.objects.create(user=user, colegio=self.colegio.colegio)
        self.client.login(username='user_col', password='pass')
        r = self.client.get('/informes/')
        self.assertEqual(r.status_code, 200)
        for fila in r.context['filas']:
            self.assertEqual(fila['colegio_nombre'], self.colegio.nombre)


# ── Pendiente al TERMINAR la clase (no al día siguiente) ──

class ListaInformesHoraFinTest(TestCase):
    """Una clase de hoy se vuelve pendiente en cuanto su bloque termina (hora_fin
    pasada), no al día siguiente. Se mockea `timezone` de la vista para fijar el
    'ahora' y evitar dependencia del reloj de pared."""

    def setUp(self):
        cache.clear()
        self.client = Client(HTTP_HOST='programacion.testserver')
        User.objects.create_superuser(username='admin_hf', password='pass')
        self.client.login(username='admin_hf', password='pass')
        self.profesor = Profesor.objects.create(nombre='Hora', apellido='Fin')
        col = Colegio.objects.create(nombre='Col HF', departamento='Santander', ciudad='BGA')
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)

    def _clase_hoy(self, hora_inicio, hora_fin):
        grado, _ = Grado.objects.get_or_create(nombre='11-1')
        materia, _ = Materia.objects.get_or_create(nombre='Lectura Crítica')
        bloque = Bloque.objects.create(colegio=self.colegio, grado=grado,
                                       hora_inicio=hora_inicio, hora_fin=hora_fin)
        return Clase.objects.create(colegio=self.colegio, bloque=bloque,
                                    fecha=date(2026, 3, 11), profesor=self.profesor,
                                    materia=materia, unidad='1')

    def _pendientes_con_ahora(self, fake_now):
        with patch('programacion.informes.views.timezone') as tz:
            tz.localdate.return_value = fake_now.date()
            tz.localtime.return_value = fake_now
            r = self.client.get('/informes/')
        return [f for f in r.context['filas'] if f['informe_id'] is None]

    def test_clase_de_hoy_terminada_aparece_pendiente(self):
        self._clase_hoy(dt_time(8, 0), dt_time(10, 0))   # terminó a las 10:00
        pendientes = self._pendientes_con_ahora(datetime(2026, 3, 11, 10, 1))
        self.assertEqual(len(pendientes), 1)

    def test_clase_de_hoy_en_curso_no_aparece_pendiente(self):
        self._clase_hoy(dt_time(10, 0), dt_time(12, 0))  # termina a las 12:00
        pendientes = self._pendientes_con_ahora(datetime(2026, 3, 11, 10, 1))
        self.assertEqual(len(pendientes), 0)


# ── Modal de diligenciamiento en la lista (portal del profesor) ──

class ListaInformesModalTest(TestCase):
    """Las filas de la lista traen los datos que el modal compartido necesita
    (clase_id/personalizada_id/profesor_id/tematica) y la caché se invalida al
    guardar — el flujo "diligenciar desde la lista → recargar" depende de ambos."""

    def setUp(self):
        cache.clear()
        self.client = Client(HTTP_HOST='programacion.testserver')
        User.objects.create_superuser(username='admin', password='pass')
        self.client.login(username='admin', password='pass')
        self.profesor = Profesor.objects.create(nombre='Rita', apellido='Vega')
        col = Colegio.objects.create(nombre='Col Modal', departamento='Santander', ciudad='BGA')
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)
        self.ayer = date.today() - timedelta(days=1)
        self.clase = crear_clase(self.colegio, self.profesor, fecha=self.ayer)

    def test_fila_pendiente_trae_datos_del_modal(self):
        r = self.client.get('/informes/')
        pendientes = [f for f in r.context['filas'] if f['informe_id'] is None]
        self.assertEqual(len(pendientes), 1)
        fila = pendientes[0]
        self.assertEqual(fila['clase_id'], self.clase.id)
        self.assertIsNone(fila['personalizada_id'])
        self.assertEqual(fila['profesor_id'], self.profesor.id)

    def test_fila_con_informe_trae_clase_id_para_precargar(self):
        crear_informe(self.profesor, self.clase, actividades='Hecho.')
        r = self.client.get('/informes/')
        completadas = [f for f in r.context['filas'] if f['informe_id'] is not None]
        self.assertEqual(len(completadas), 1)
        self.assertEqual(completadas[0]['clase_id'], self.clase.id)
        self.assertEqual(completadas[0]['profesor_id'], self.profesor.id)

    def test_guardar_invalida_la_cache_de_la_lista(self):
        # 1.ª visita: la clase aparece pendiente y la respuesta queda cacheada
        r1 = self.client.get('/informes/')
        self.assertFalse(r1.context['filas'][0]['completado'])

        # Guardar el informe vía AJAX (mismo flujo del modal)
        r = self.client.post(
            '/informes/ajax/guardar/',
            data=json.dumps({
                'clase_id': self.clase.id,
                'profesor_id': self.profesor.id,
                'fecha_iso': str(self.ayer),
                'colegio_nombre': 'Col Modal',
                'grado': '11-1',
                'materia': 'Lectura Crítica',
                'tematica': '1',
                'material': 'Saberes 11 Oro',
                'actividades': 'Taller de lectura.',
            }),
            content_type='application/json',
        )
        self.assertTrue(json.loads(r.content)['ok'])

        # 2.ª visita: la fila debe reflejar el informe (la caché rotó de generación)
        r2 = self.client.get('/informes/')
        self.assertTrue(r2.context['filas'][0]['completado'])
        self.assertIsNotNone(r2.context['filas'][0]['informe_id'])


# ── Menú lateral por rol (portal del profesor) ────────────────

class MenuPortalProfesorTest(TestCase):
    """base.html: el perfil de profesor tiene menú propio (Cronograma / Informes /
    Pagos); gestor de colegio y staff conservan el suyo."""

    def setUp(self):
        cache.clear()
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.col = Colegio.objects.create(nombre='Col Menú', departamento='Santander', ciudad='BGA')
        ColegioAnio.objects.create(colegio=self.col, anio=2026, activo=True)
        self.profesor = Profesor.objects.create(nombre='Mario', apellido='Lugo')

    def test_profesor_ve_menu_propio_con_pagos(self):
        user = User.objects.create_user(username='prof_menu', password='pass')
        UsuarioProfesor.objects.create(user=user, profesor=self.profesor)
        self.client.login(username='prof_menu', password='pass')
        html = self.client.get('/informes/').content.decode()
        self.assertIn('Cronograma', html)
        self.assertIn('Informes', html)
        self.assertIn('/profesores/pagos/', html)  # portal de pagos del profesor (F4)
        self.assertNotIn('Configuración', html)  # nada del menú de staff

    def test_gestor_colegio_mantiene_su_menu(self):
        user = User.objects.create_user(username='gestor_menu', password='pass')
        UsuarioColegio.objects.create(user=user, colegio=self.col)
        self.client.login(username='gestor_menu', password='pass')
        html = self.client.get('/informes/').content.decode()
        self.assertIn('Col Menú', html)       # acceso directo a su colegio
        self.assertIn('Informes', html)
        self.assertNotIn('Cronograma', html)
        self.assertNotIn('/profesores/pagos/', html)  # el portal de pagos es solo del profesor

    def test_staff_mantiene_menu_completo(self):
        User.objects.create_superuser(username='admin_menu', password='pass')
        self.client.login(username='admin_menu', password='pass')
        html = self.client.get('/informes/').content.decode()
        self.assertIn('Operaciones', html)
        self.assertIn('Configuración', html)
        self.assertNotIn('/profesores/pagos/', html)


# ── Acceso por perfil a lista de informes ────────────────────

class ListaInformesAccesoTest(TestCase):

    def setUp(self):
        cache.clear()
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.admin = User.objects.create_superuser('admin_inf', password='pass')
        col = Colegio.objects.create(
            nombre='Col Inf', departamento='Santander', ciudad='BGA'
        )
        self.colegio = col
        self.colegio_anio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)
        otro_col = Colegio.objects.create(
            nombre='Otro Colegio', departamento='Valle', ciudad='Cali'
        )
        self.otro_anio = ColegioAnio.objects.create(colegio=otro_col, anio=2026, activo=True)
        self.profesor = Profesor.objects.create(nombre='Ana', apellido='López')
        user_col  = User.objects.create_user('user_col_inf', password='pass')
        user_prof = User.objects.create_user('user_prof_inf', password='pass')
        UsuarioColegio.objects.create(user=user_col, colegio=self.colegio)
        UsuarioProfesor.objects.create(user=user_prof, profesor=self.profesor)
        crear_informe(self.profesor, crear_clase(self.colegio_anio, self.profesor),
                      actividades='Álgebra.')
        crear_informe(self.profesor, crear_clase(self.otro_anio, self.profesor),
                      actividades='Mecánica.')

    def test_admin_ve_todos_los_informes(self):
        self.client.login(username='admin_inf', password='pass')
        r = self.client.get('/informes/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['filas']), 2)

    def test_usuario_colegio_solo_ve_sus_informes(self):
        self.client.login(username='user_col_inf', password='pass')
        r = self.client.get('/informes/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['filas']), 1)
        self.assertEqual(r.context['filas'][0]['colegio_nombre'], 'Col Inf')

    def test_usuario_profesor_solo_ve_sus_informes(self):
        self.client.login(username='user_prof_inf', password='pass')
        r = self.client.get('/informes/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['filas']), 2)


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

    def test_get_no_elimina(self):
        # Regresión: la vista es destructiva, un GET no debe ejecutarla (405).
        self.client.login(username='admin', password='pass')
        r = self.client.get(f'/informes/{self.informe.id}/eliminar/')
        self.assertEqual(r.status_code, 405)
        self.assertTrue(Informe.objects.filter(id=self.informe.id).exists())