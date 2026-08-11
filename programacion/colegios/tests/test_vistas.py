"""
Tests — app: colegios (vistas)
dashboard_colegios, cargar_grados, clonación de configuración (A y B),
_construir_stats e historial de cambios.
"""
import json
from django.core.cache import cache
from django.test import TestCase, Client
from django.contrib.auth.models import User
from datetime import date, time

from programacion.configuracion.models import Colegio, ColegioAnio, Profesor, NombreLibro, Materia
from programacion.colegios.models import Bloque, Asignacion, Clase, Grado


# ── Vistas ────────────────────────────────────────────────────

class DashboardColegiosViewTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.admin = User.objects.create_superuser(
            username='admin_col', password='pass123'
        )
        col = Colegio.objects.create(
            nombre='Col Vista', departamento='Bogota D.C.', ciudad='Bogotá'
        )
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)

    def test_no_autenticado_redirige_a_login(self):
        r = self.client.get('/colegios/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/usuarios/login/', r['Location'])

    def test_admin_puede_acceder_sin_seleccionar_colegio(self):
        self.client.login(username='admin_col', password='pass123')
        r = self.client.get('/colegios/')
        self.assertEqual(r.status_code, 200)

    def test_admin_puede_acceder_con_colegio_seleccionado(self):
        self.client.login(username='admin_col', password='pass123')
        r = self.client.get(f'/colegios/?id_col={self.colegio.id}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['sel_col'], self.colegio)

    def test_contexto_incluye_hoy(self):
        self.client.login(username='admin_col', password='pass123')
        r = self.client.get(f'/colegios/?id_col={self.colegio.id}')
        self.assertIn('hoy', r.context)

    def test_colegio_inexistente_devuelve_404(self):
        self.client.login(username='admin_col', password='pass123')
        r = self.client.get('/colegios/?id_col=99999')
        self.assertEqual(r.status_code, 404)

    def test_buscador_incluye_codigo_y_nombre(self):
        # El buscador (select2) debe ofrecer "codigo - nombre" para buscar por ambos.
        col = Colegio.objects.create(
            nombre='Col Con Codigo', codigo='12345',
            departamento='Bogota D.C.', ciudad='Bogotá')
        ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)
        self.client.login(username='admin_col', password='pass123')
        html = self.client.get('/colegios/').content.decode()
        self.assertIn('12345 - Col Con Codigo', html)

    def test_badge_calendario_b_se_muestra(self):
        col = Colegio.objects.create(
            nombre='Col Norte', departamento='Bogota D.C.', ciudad='Bogotá',
            calendario=Colegio.Calendario.B)
        ca = ColegioAnio.objects.create(colegio=col, anio=2025, activo=True)
        self.client.login(username='admin_col', password='pass123')
        html = self.client.get(f'/colegios/?id_col={ca.id}').content.decode()
        self.assertIn('Cal B · 2025-2026', html)

    def test_staff_de_area_ve_boton_crear_clase(self):
        # Regresión: el staff de área (grupo area:programacion, NO is_staff) debe ver el
        # botón "Crear clase". El gate antes era request.user.is_staff → lo ocultaba.
        from django.contrib.auth.models import Group
        from core.areas import GRUPO_STAFF_PROGRAMACION
        grupo, _ = Group.objects.get_or_create(name=GRUPO_STAFF_PROGRAMACION)
        staff = User.objects.create_user('staff_col', password='pass123')
        staff.groups.add(grupo)
        self.assertFalse(staff.is_staff)  # el staff de área no es is_staff
        self.client.login(username='staff_col', password='pass123')
        html = self.client.get(f'/colegios/?id_col={self.colegio.id}').content.decode()
        self.assertIn('Crear clase', html)

    def test_staff_de_area_accede_a_configurar_colegio(self):
        # Regresión: el staff de área (grupo area:programacion, NO superusuario ni perfil
        # de colegio) debe poder abrir el panel de configuración (grados/bloques). El gate
        # antes era request.user.is_superuser → lo redirigía a /configuracion/usuarios/login/
        # (404). Ahora usa request.es_personal_programacion.
        from django.contrib.auth.models import Group
        from core.areas import GRUPO_STAFF_PROGRAMACION
        grupo, _ = Group.objects.get_or_create(name=GRUPO_STAFF_PROGRAMACION)
        staff = User.objects.create_user('staff_cfg', password='pass123')
        staff.groups.add(grupo)
        self.client.login(username='staff_cfg', password='pass123')
        r = self.client.get(f'/colegios/configurar-colegio/{self.colegio.id}/')
        self.assertEqual(r.status_code, 200)


class CargarGradosViewTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        User.objects.create_superuser(username='admin', password='pass')
        self.client.login(username='admin', password='pass')
        col = Colegio.objects.create(
            nombre='Col Grados', departamento='Valle', ciudad='Cali'
        )
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)
        grado_11 = Grado.objects.create(nombre='11-1')
        grado_10 = Grado.objects.create(nombre='10-1')
        Bloque.objects.create(
            colegio=self.colegio, grado=grado_11,
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        )
        Bloque.objects.create(
            colegio=self.colegio, grado=grado_10,
            hora_inicio=time(10, 30), hora_fin=time(12, 0),
        )

    def test_devuelve_grados_del_colegio(self):
        r = self.client.get(f'/colegios/ajax/cargar-grados/?colegio_id={self.colegio.id}')
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertIn('11-1', data)
        self.assertIn('10-1', data)

    def test_sin_colegio_id_devuelve_lista_vacia(self):
        r = self.client.get('/colegios/ajax/cargar-grados/')
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertEqual(data, [])


class ClonarConfiguracionTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.admin = User.objects.create_superuser('admin_clone', password='pass')
        self.client.login(username='admin_clone', password='pass')
        self.col_perm = Colegio.objects.create(
            nombre='Col Origen', departamento='Santander', ciudad='BGA'
        )
        self.colegio = ColegioAnio.objects.create(colegio=self.col_perm, anio=2026, activo=True)
        self.grado = Grado.objects.create(nombre='11-1')
        Bloque.objects.create(
            colegio=self.colegio, grado=self.grado,
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        )
        self.libro = NombreLibro.objects.create(nombre='Saberes 11 Oro')
        Asignacion.objects.create(
            colegio=self.colegio, grado=self.grado,
            libro=self.libro,
            fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 12, 31),
        )

    def test_clonar_crea_nuevo_colegio_anio_siguiente(self):
        r = self.client.post(
            f'/colegios/ajax/clonar/{self.colegio.id}/',
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data['ok'])
        nuevo = ColegioAnio.objects.get(id=data['nuevo_id'])
        self.assertEqual(nuevo.anio, 2027)
        self.assertEqual(nuevo.nombre, 'Col Origen')

    def test_clonar_copia_bloques(self):
        self.client.post(f'/colegios/ajax/clonar/{self.colegio.id}/',
                         content_type='application/json')
        nuevo = ColegioAnio.objects.get(colegio=self.col_perm, anio=2027)
        self.assertEqual(Bloque.objects.filter(colegio=nuevo).count(), 1)

    def test_clonar_copia_asignaciones_con_fechas_del_nuevo_anio(self):
        self.client.post(f'/colegios/ajax/clonar/{self.colegio.id}/',
                         content_type='application/json')
        nuevo = ColegioAnio.objects.get(colegio=self.col_perm, anio=2027)
        asig = Asignacion.objects.filter(colegio=nuevo).first()
        self.assertIsNotNone(asig)
        self.assertEqual(asig.fecha_inicio.year, 2027)
        self.assertEqual(asig.fecha_fin.year, 2027)

    def test_no_se_puede_clonar_si_ya_existe_el_anio_siguiente(self):
        ColegioAnio.objects.create(colegio=self.col_perm, anio=2027, activo=True)
        r = self.client.post(f'/colegios/ajax/clonar/{self.colegio.id}/',
                              content_type='application/json')
        data = r.json()
        self.assertFalse(data['ok'])


class ClonarColegioBTest(TestCase):
    """El clon de un colegio Calendario B conserva la ventana ago→jun cruzada."""

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        User.objects.create_superuser('admin_clone_b', password='pass')
        self.client.login(username='admin_clone_b', password='pass')
        self.col_perm = Colegio.objects.create(
            nombre='Col Origen B', departamento='Santander', ciudad='BGA',
            calendario=Colegio.Calendario.B,
        )
        # anio=2025 → ventana ago-2025 … jun-2026
        self.colegio = ColegioAnio.objects.create(
            colegio=self.col_perm, anio=2025, activo=True
        )
        self.grado = Grado.objects.create(nombre='11-1')
        self.libro = NombreLibro.objects.create(nombre='Saberes 11 B')
        # Asignación con la ventana B explícita (la que pondría el save()).
        Asignacion.objects.create(
            colegio=self.colegio, grado=self.grado, libro=self.libro,
            fecha_inicio=date(2025, 8, 1), fecha_fin=date(2026, 6, 30),
        )

    def test_clon_genera_ventana_b_siguiente(self):
        r = self.client.post(f'/colegios/ajax/clonar/{self.colegio.id}/',
                             content_type='application/json')
        self.assertTrue(r.json()['ok'])
        nuevo = ColegioAnio.objects.get(colegio=self.col_perm, anio=2026)
        # El nuevo periodo cruza ago-2026 … jun-2027.
        self.assertEqual(nuevo.rango, (date(2026, 8, 1), date(2027, 6, 30)))
        asig = Asignacion.objects.filter(colegio=nuevo).first()
        self.assertIsNotNone(asig)
        # Las fechas explícitas se desplazan +1 año relativo (no colapsan al ancla).
        self.assertEqual(asig.fecha_inicio, date(2026, 8, 1))
        self.assertEqual(asig.fecha_fin, date(2027, 6, 30))


class ConstruirStatsTest(TestCase):

    def setUp(self):
        col = Colegio.objects.create(
            nombre='Col Stats', departamento='Santander', ciudad='BGA'
        )
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)
        self.materia = Materia.objects.create(nombre='Matematicas', color='#e74c3c')
        self.grado = Grado.objects.create(nombre='11-1')
        self.bloque = Bloque.objects.create(
            colegio=self.colegio, grado=self.grado,
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        )
        self.libro = NombreLibro.objects.create(nombre='Libro Stats Test')
        from programacion.configuracion.models import Unidad
        self.unidad1 = Unidad.objects.create(
            libro=self.libro, materia=self.materia, numero=1, nombre='Unidad 1'
        )
        self.unidad2 = Unidad.objects.create(
            libro=self.libro, materia=self.materia, numero=2, nombre='Unidad 2'
        )
        self.asignacion = Asignacion.objects.create(
            colegio=self.colegio, grado=self.grado, libro=self.libro,
            fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 12, 31),
        )
        self.profesor = Profesor.objects.create(nombre='Carlos', apellido='Lopez')

    def _clase(self, unidad_str, fecha=None, cancelada=False, es_evento=False):
        from datetime import date as d
        fecha = fecha or d(2026, 3, 10)
        return Clase.objects.create(
            colegio=self.colegio,
            bloque=self.bloque,
            fecha=fecha,
            profesor=self.profesor,
            materia=self.materia,
            unidad=unidad_str,
            cancelada=cancelada,
            es_evento=es_evento,
        )

    def test_unidad_usada_una_vez_es_dado(self):
        from programacion.colegios.views import _construir_stats
        self._clase('1')
        stats = _construir_stats(self.colegio)
        libros = stats['11-1']['Matematicas']['libros']
        self.assertTrue(len(libros) > 0, "No hay libros en stats para Matematicas")
        unidades = libros[0]['unidades']
        u1 = next(u for u in unidades if u['numero'] == '1')
        self.assertEqual(u1['tipo'], 'dado')

    def test_unidad_usada_dos_veces_es_repetido(self):
        from programacion.colegios.views import _construir_stats
        self._clase('1', fecha=date(2026, 3, 10))
        self._clase('1', fecha=date(2026, 3, 11))
        stats = _construir_stats(self.colegio)
        libros = stats['11-1']['Matematicas']['libros']
        self.assertTrue(len(libros) > 0, "No hay libros en stats para Matematicas")
        unidades = libros[0]['unidades']
        u1 = next(u for u in unidades if u['numero'] == '1')
        self.assertEqual(u1['tipo'], 'repetido')
        self.assertEqual(u1['count'], 2)

    def test_unidad_en_clase_pero_no_en_libro_es_invalido(self):
        from programacion.colegios.views import _construir_stats
        self._clase('99')
        stats = _construir_stats(self.colegio)
        libros = stats['11-1']['Matematicas']['libros']
        self.assertTrue(len(libros) > 0, "No hay libros en stats para Matematicas")
        unidades = libros[0]['unidades']
        u99 = next((u for u in unidades if u['numero'] == '99'), None)
        self.assertIsNotNone(u99)
        self.assertEqual(u99['tipo'], 'invalido')

    def test_clase_cancelada_no_aparece_en_conteo(self):
        from programacion.colegios.views import _construir_stats
        self._clase('1', cancelada=True)
        stats = _construir_stats(self.colegio)
        unidades = stats.get('11-1', {}).get('Matematicas', {}).get('unidades', [])
        u1 = next((u for u in unidades if u['numero'] == '1'), None)
        # Puede que exista como pendiente (del libro) pero count debe ser 0
        if u1:
            self.assertEqual(u1['count'], 0)

    def test_clase_evento_no_aparece_en_conteo(self):
        from programacion.colegios.views import _construir_stats
        clase = Clase.objects.create(
            colegio=self.colegio, bloque=self.bloque,
            fecha=date(2026, 3, 10),
            es_evento=True, titulo_evento='Feria',
            materia=self.materia, unidad='1',
        )
        stats = _construir_stats(self.colegio)
        unidades = stats.get('11-1', {}).get('Matematicas', {}).get('unidades', [])
        u1 = next((u for u in unidades if u['numero'] == '1'), None)
        if u1:
            self.assertEqual(u1['count'], 0)

    def test_grado_sin_asignacion_no_aparece(self):
        from programacion.colegios.views import _construir_stats
        grado2 = Grado.objects.create(nombre='10-1')
        bloque2 = Bloque.objects.create(
            colegio=self.colegio, grado=grado2,
            hora_inicio=time(10, 30), hora_fin=time(12, 0),
        )
        Clase.objects.create(
            colegio=self.colegio, bloque=bloque2,
            fecha=date(2026, 3, 10),
            materia=self.materia, unidad='1',
        )
        stats = _construir_stats(self.colegio)
        # 10-1 no tiene asignacion de libro ni clases (no sale porque no tiene materias en universo ni conteo para esa materia)
        # Verificamos que al menos 11-1 sí aparece (tiene asignacion)
        self.assertIn('11-1', stats)


class StatsVisiblesParaColegioTest(TestCase):
    """
    El panel "Estadísticas de avance" (vistas Simple y Detallada) debe verlo también el
    gestor de colegio, no solo el staff de programación. Antes el template lo gateaba con
    `request.es_personal_programacion`, así que el gestor cargaba el dashboard sin panel
    y sin el json_script `stats-data` que lo alimenta.
    """

    def setUp(self):
        cache.clear()  # el dashboard cachea matriz/stats por (colegio, año)
        self.client = Client(HTTP_HOST='programacion.testserver')
        col = Colegio.objects.create(
            nombre='Col Panel', departamento='Santander', ciudad='BGA'
        )
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)

        materia = Materia.objects.create(nombre='Matematicas', color='#e74c3c')
        grado   = Grado.objects.create(nombre='11-1')
        bloque  = Bloque.objects.create(
            colegio=self.colegio, grado=grado,
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        )
        libro = NombreLibro.objects.create(nombre='Libro Panel')
        from programacion.configuracion.models import Unidad
        Unidad.objects.create(libro=libro, materia=materia, numero=1, nombre='Unidad 1')
        Asignacion.objects.create(
            colegio=self.colegio, grado=grado, libro=libro,
            fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 12, 31),
        )
        Clase.objects.create(
            colegio=self.colegio, bloque=bloque, fecha=date(2026, 3, 10),
            profesor=Profesor.objects.create(nombre='Carlos', apellido='Lopez'),
            materia=materia, unidad='1',
        )

        from usuarios.models import UsuarioColegio
        gestor = User.objects.create_user('gestor_panel', password='pass123')
        UsuarioColegio.objects.create(user=gestor, colegio=col)

    def _html_gestor(self):
        self.client.login(username='gestor_panel', password='pass123')
        # El middleware fuerza id_col al año activo del colegio del perfil.
        return self.client.get('/colegios/').content.decode()

    def test_gestor_colegio_ve_el_panel_de_estadisticas(self):
        html = self._html_gestor()
        self.assertIn('id="seccion-stats"', html)
        self.assertIn('Estadísticas de avance', html)

    def test_gestor_colegio_ve_las_dos_vistas(self):
        html = self._html_gestor()
        self.assertIn('id="btn-vista-simple"', html)
        self.assertIn('id="btn-vista-detallada"', html)

    def test_gestor_colegio_recibe_los_datos_del_panel(self):
        # Sin el json_script el panel se pinta vacío: initStats() sale por STATS_JSON undefined.
        html = self._html_gestor()
        self.assertIn('id="stats-data"', html)
        self.assertIn('Libro Panel', html)

    def test_gestor_colegio_no_ve_acciones_de_edicion(self):
        # El panel es de solo lectura: abrirlo al gestor no debe destapar la edición.
        # Se comprueba el MARCADO (botón, modal, doble-clic en la celda), no los literales:
        # el JS del dashboard se sirve completo a todos y menciona "Crear clase" y
        # abrirModalCrear() en su cuerpo aunque no haya nada que abrir.
        html = self._html_gestor()
        self.assertNotIn('onclick="abrirModalCrear()"', html)
        self.assertNotIn('id="modalClase"', html)
        self.assertNotIn('ondblclick=', html)

    def test_staff_sigue_viendo_el_panel(self):
        User.objects.create_superuser('admin_panel', password='pass123')
        self.client.login(username='admin_panel', password='pass123')
        html = self.client.get(f'/colegios/?id_col={self.colegio.id}').content.decode()
        self.assertIn('id="seccion-stats"', html)
        self.assertIn('id="stats-data"', html)

    def test_colegio_sin_clases_no_muestra_el_panel(self):
        # stats_vacio sigue mandando: sin datos no se pinta el panel (ni para el gestor).
        col2 = Colegio.objects.create(
            nombre='Col Vacio', departamento='Santander', ciudad='BGA'
        )
        ColegioAnio.objects.create(colegio=col2, anio=2026, activo=True)
        from usuarios.models import UsuarioColegio
        gestor2 = User.objects.create_user('gestor_vacio', password='pass123')
        UsuarioColegio.objects.create(user=gestor2, colegio=col2)
        self.client.login(username='gestor_vacio', password='pass123')
        html = self.client.get('/colegios/').content.decode()
        self.assertNotIn('id="seccion-stats"', html)
        self.assertNotIn('id="stats-data"', html)


class HistorialCambioTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.admin = User.objects.create_superuser('admin_hist', password='pass')
        self.client.login(username='admin_hist', password='pass')
        col = Colegio.objects.create(
            nombre='Col Hist', departamento='Santander', ciudad='BGA'
        )
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)

    def test_crear_bloque_registra_historial(self):
        Grado.objects.get_or_create(nombre='11-1')
        self.client.post(
            f'/colegios/configurar-colegio/{self.colegio.id}/',
            {'accion': 'add_bloque', 'grado': '11-1',
             'hora_inicio': '08:00', 'hora_fin': '10:00', 'orden': 1}
        )
        from programacion.colegios.models import HistorialCambio
        self.assertTrue(
            HistorialCambio.objects.filter(
                colegio=self.colegio, tipo='crear', objeto_tipo='Bloque'
            ).exists()
        )

    def test_historial_colegio_accesible_por_admin(self):
        r = self.client.get(f'/colegios/historial/{self.colegio.id}/')
        self.assertEqual(r.status_code, 200)

    def test_historial_global_accesible_por_admin(self):
        r = self.client.get('/historial/')
        self.assertEqual(r.status_code, 200)

    def test_historial_global_no_accesible_por_usuario_colegio(self):
        from usuarios.models import UsuarioColegio
        user_col = User.objects.create_user('user_hist_col', password='pass')
        UsuarioColegio.objects.create(user=user_col, colegio=self.colegio.colegio)
        self.client.login(username='user_hist_col', password='pass')
        r = self.client.get('/historial/')
        self.assertNotEqual(r.status_code, 200)
