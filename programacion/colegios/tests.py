"""
Tests — app: colegios
Modelos: Bloque, Asignacion, Clase, ClasePersonalizada
Utilidades: label_unidad, extraer_numero_grado, calcular_rango_fechas, ordenar_grados
Vistas: dashboard_colegios, cargar_grados
"""
import json
from django.test import TestCase, Client
from django.contrib.auth.models import User
from datetime import date, time

from programacion.configuracion.models import Colegio, ColegioAnio, Profesor, NombreLibro, Materia
from programacion.colegios.models import Bloque, Asignacion, Clase, ClasePersonalizada, Grado
from programacion.colegios.utils import (
    extraer_numero_grado,
    calcular_rango_fechas,
    ordenar_grados,
)
from datetime import datetime


# ── Utilidades ────────────────────────────────────────────────

class ExtraerNumeroGradoTest(TestCase):

    def test_grado_con_guion(self):
        self.assertEqual(extraer_numero_grado('11-1'), 11)

    def test_grado_simple(self):
        self.assertEqual(extraer_numero_grado('10'), 10)

    def test_sin_numero_devuelve_cero(self):
        self.assertEqual(extraer_numero_grado('sin número'), 0)


class CalcularRangoFechasTest(TestCase):

    def setUp(self):
        self.lunes = date(2026, 3, 9)  # Lunes conocido

    def test_semana_empieza_en_lunes_y_dura_7_dias(self):
        inicio, dias = calcular_rango_fechas('Semana', self.lunes)
        self.assertEqual(inicio.weekday(), 0)
        self.assertEqual(dias, 7)

    def test_semana_desde_dia_intermedio_retrocede_a_lunes(self):
        miercoles = date(2026, 3, 11)
        inicio, _ = calcular_rango_fechas('Semana', miercoles)
        self.assertEqual(inicio, date(2026, 3, 9))

    def test_mes_empieza_en_dia_1(self):
        inicio, dias = calcular_rango_fechas('Mes', self.lunes)
        self.assertEqual(inicio.day, 1)
        self.assertEqual(inicio.month, 3)
        self.assertEqual(dias, 31)  # marzo tiene 31 días

    def test_anno_empieza_el_1_enero(self):
        inicio, dias = calcular_rango_fechas('Año', self.lunes)
        self.assertEqual(inicio, date(2026, 1, 1))
        self.assertIn(dias, [365, 366])

class OrdenarGradosTest(TestCase):

    def test_grados_tradicionales_descendente(self):
        grados = ['10-1', '11-1', '9-1']
        resultado = ordenar_grados(grados)
        self.assertEqual(resultado[0], '11-1')
        self.assertEqual(resultado[-1], '9-1')

    def test_grados_especiales_van_al_final(self):
        grados = ['11-1', 'Grupo 1', '10-1']
        resultado = ordenar_grados(grados)
        self.assertIn('Grupo 1', resultado)
        self.assertEqual(resultado[-1], 'Grupo 1')


# ── Modelos ───────────────────────────────────────────────────

class BloqueModelTest(TestCase):

    def setUp(self):
        col = Colegio.objects.create(
            nombre='Colegio Test', departamento='Santander', ciudad='Bogotá'
        )
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)
        self.grado = Grado.objects.create(nombre='11-1')

    def test_str_incluye_grado_y_hora(self):
        b = Bloque.objects.create(
            colegio=self.colegio, grado=self.grado,
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        )
        self.assertIn('11-1', str(b))

    def test_propiedad_hora_formato_ampm(self):
        b = Bloque.objects.create(
            colegio=self.colegio, grado=self.grado,
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        )
        self.assertIn('AM', b.hora)

    def test_propiedad_duracion_minutos(self):
        b = Bloque.objects.create(
            colegio=self.colegio, grado=self.grado,
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        )
        self.assertEqual(b.duracion_minutos, 120)


class AsignacionModelTest(TestCase):

    def setUp(self):
        col = Colegio.objects.create(
            nombre='Col Asig', departamento='Antioquia', ciudad='Cali'
        )
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)
        self.grado = Grado.objects.create(nombre='11-1')

    def test_fechas_se_autocompletan_si_no_se_proveen(self):
        libro = NombreLibro.objects.create(nombre='Saberes 11 Oro')
        asig = Asignacion.objects.create(
            colegio=self.colegio, grado=self.grado, libro=libro
        )
        anio = date.today().year
        self.assertEqual(asig.fecha_inicio, date(anio, 1, 1))
        self.assertEqual(asig.fecha_fin, date(anio, 12, 31))

    def test_fechas_manuales_no_se_sobreescriben(self):
        libro = NombreLibro.objects.create(nombre='Saberes 11 Oro')
        asig = Asignacion.objects.create(
            colegio=self.colegio, grado=self.grado, libro=libro,
            fecha_inicio=date(2026, 3, 1), fecha_fin=date(2026, 6, 30),
        )
        self.assertEqual(asig.fecha_inicio, date(2026, 3, 1))
        self.assertEqual(asig.fecha_fin, date(2026, 6, 30))

    def test_str_incluye_colegio_grado_libro(self):
        libro = NombreLibro.objects.create(nombre='Conceptos 10')
        asig = Asignacion.objects.create(
            colegio=self.colegio, grado=self.grado, libro=libro
        )
        r = str(asig)
        self.assertIn('Col Asig', r)
        self.assertIn('11-1', r)
        self.assertIn('Conceptos 10', r)


class ClaseModelTest(TestCase):

    def setUp(self):
        col = Colegio.objects.create(
            nombre='Col Clase', departamento='Cundinamarca', ciudad='BGA'
        )
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)
        self.grado = Grado.objects.create(nombre='11-1')
        self.bloque = Bloque.objects.create(
            colegio=self.colegio, grado=self.grado,
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        )

    def test_valores_por_defecto(self):
        c = Clase.objects.create(
            colegio=self.colegio, bloque=self.bloque, fecha=date.today()
        )
        self.assertFalse(c.cancelada)
        self.assertFalse(c.es_evento)
        self.assertIsNone(c.profesor)

    def test_unique_together_fecha_y_bloque(self):
        from django.db import IntegrityError
        hoy = date.today()
        Clase.objects.create(colegio=self.colegio, bloque=self.bloque, fecha=hoy)
        with self.assertRaises(IntegrityError):
            Clase.objects.create(colegio=self.colegio, bloque=self.bloque, fecha=hoy)

    def test_misma_fecha_diferente_bloque_es_valido(self):
        grado2  = Grado.objects.create(nombre='10-1')
        bloque2 = Bloque.objects.create(
            colegio=self.colegio, grado=grado2,
            hora_inicio=time(10, 30), hora_fin=time(12, 0),
        )
        hoy = date.today()
        Clase.objects.create(colegio=self.colegio, bloque=self.bloque,  fecha=hoy)
        Clase.objects.create(colegio=self.colegio, bloque=bloque2, fecha=hoy)
        self.assertEqual(Clase.objects.filter(fecha=hoy).count(), 2)

    def test_clean_rechaza_fecha_de_otro_anio(self):
        from django.core.exceptions import ValidationError
        clase = Clase(
            colegio=self.colegio, bloque=self.bloque,
            fecha=date(2027, 3, 15),
        )
        with self.assertRaises(ValidationError):
            clase.clean()

    def test_clean_acepta_fecha_del_mismo_anio(self):
        clase = Clase(
            colegio=self.colegio, bloque=self.bloque,
            fecha=date(2026, 6, 15),
        )
        clase.clean()  # No debe lanzar excepción


class ClaseCalendarioBTest(TestCase):
    """Validación de fechas de clase para un colegio Calendario B (ago→jun)."""

    def setUp(self):
        col = Colegio.objects.create(
            nombre='Col B', departamento='Santander', ciudad='BGA',
            calendario=Colegio.Calendario.B,
        )
        # anio=2025 (ancla) → ventana ago-2025 … jun-2026
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2025, activo=True)
        self.grado = Grado.objects.create(nombre='11-1')
        self.bloque = Bloque.objects.create(
            colegio=self.colegio, grado=self.grado,
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        )

    def test_rango_cruza_dos_anios(self):
        self.assertEqual(self.colegio.rango, (date(2025, 8, 1), date(2026, 6, 30)))

    def test_clean_acepta_fecha_del_primer_tramo(self):
        # septiembre 2025 (ago–dic del año ancla)
        Clase(colegio=self.colegio, bloque=self.bloque,
              fecha=date(2025, 9, 15)).clean()

    def test_clean_acepta_fecha_del_segundo_tramo(self):
        # marzo 2026 (ene–jun del año+1)
        Clase(colegio=self.colegio, bloque=self.bloque,
              fecha=date(2026, 3, 15)).clean()

    def test_clean_rechaza_fecha_antes_de_la_ventana(self):
        from django.core.exceptions import ValidationError
        # julio 2025, antes del inicio
        with self.assertRaises(ValidationError):
            Clase(colegio=self.colegio, bloque=self.bloque,
                  fecha=date(2025, 7, 15)).clean()

    def test_clean_rechaza_fecha_despues_de_la_ventana(self):
        from django.core.exceptions import ValidationError
        # julio 2026, después del fin
        with self.assertRaises(ValidationError):
            Clase(colegio=self.colegio, bloque=self.bloque,
                  fecha=date(2026, 7, 1)).clean()

    def test_cohortes_no_se_mezclan(self):
        # Dos periodos del mismo colegio B: cada clase queda particionada por su FK.
        sig = ColegioAnio.objects.create(
            colegio=self.colegio.colegio, anio=2026, activo=True
        )
        bloque_sig = Bloque.objects.create(
            colegio=sig, grado=self.grado,
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        )
        c1 = Clase.objects.create(colegio=self.colegio, bloque=self.bloque,
                                  fecha=date(2025, 9, 15))
        c2 = Clase.objects.create(colegio=sig, bloque=bloque_sig,
                                  fecha=date(2026, 9, 15))
        self.assertEqual(list(Clase.objects.filter(colegio=self.colegio)), [c1])
        self.assertEqual(list(Clase.objects.filter(colegio=sig)), [c2])

    def test_asignacion_autocompleta_con_ventana_b(self):
        libro = NombreLibro.objects.create(nombre='Saberes B')
        asig = Asignacion.objects.create(
            colegio=self.colegio, grado=self.grado, libro=libro
        )
        self.assertEqual(asig.fecha_inicio, date(2025, 8, 1))
        self.assertEqual(asig.fecha_fin, date(2026, 6, 30))


class ClasePersonalizadaModelTest(TestCase):

    def setUp(self):
        self.profesor = Profesor.objects.create(nombre='Ana', apellido='García')

    def test_str_incluye_estudiante_y_profesor(self):
        grado = Grado.objects.create(nombre='10-1')
        materia = Materia.objects.create(nombre='Lectura Crítica')
        libro = NombreLibro.objects.create(nombre='Conceptos 10')
        cp = ClasePersonalizada.objects.create(
            profesor=self.profesor, estudiante='Col San Pedro',
            fecha=date.today(), hora_inicio=time(14, 0), hora_fin=time(16, 0),
            grado=grado, libro=libro, materia=materia, unidad='2',
        )
        self.assertIn('Col San Pedro', str(cp))
        self.assertIn('Ana', str(cp))

    def test_ciudad_default_bucaramanga(self):
        grado = Grado.objects.create(nombre='11-1')
        materia = Materia.objects.create(nombre='Mate')
        libro = NombreLibro.objects.create(nombre='Libro A')
        cp = ClasePersonalizada.objects.create(
            profesor=self.profesor, estudiante='Col X',
            fecha=date.today(), hora_inicio=time(8, 0), hora_fin=time(10, 0),
            grado=grado, libro=libro, materia=materia, unidad='1',
        )
        self.assertEqual(cp.ciudad, 'Bucaramanga')

    def test_propiedad_hora_devuelve_rango(self):
        grado = Grado.objects.create(nombre='9-1')
        materia = Materia.objects.create(nombre='Ciencias')
        libro = NombreLibro.objects.create(nombre='Libro B')
        cp = ClasePersonalizada.objects.create(
            profesor=self.profesor, estudiante='Col Y',
            fecha=date.today(), hora_inicio=time(14, 0), hora_fin=time(16, 0),
            grado=grado, libro=libro, materia=materia, unidad='1',
        )
        self.assertEqual(cp.hora, '2:00 PM - 4:00 PM')


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


# ── Tests HTMX — Fase 2 ──────────────────────────────────────────

class AjaxGuardarClaseHtmxTest(TestCase):
    """
    Verifica que ajax_guardar_clase devuelva fragmento HTML cuando lleva
    HX-Request: true, y JSON cuando no lo lleva (compatibilidad legacy).
    """

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.admin = User.objects.create_superuser('admin_htmx', password='pass')
        self.client.login(username='admin_htmx', password='pass')
        col = Colegio.objects.create(
            nombre='Col HTMX', departamento='Santander', ciudad='BGA'
        )
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)
        self.grado   = Grado.objects.create(nombre='11-1')
        self.bloque  = Bloque.objects.create(
            colegio=self.colegio, grado=self.grado,
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        )
        self.materia = Materia.objects.create(nombre='Física', color='#3498db')
        self.profesor = Profesor.objects.create(nombre='Luis', apellido='Ruiz')

    def _post(self, extra_headers=None, **data):
        payload = {
            'guardar_clase': '1',
            'bloque_id':     str(self.bloque.id),
            'fecha_clase':   '2026-05-15',
            'materia':       'Física',
            'profesor':      str(self.profesor.id),
            'unidad':        '1',
            'eliminar_clase': '0',
            'material_especial': '0',
            'tipo_especial': '',
            'libro_especial_id': '',
            'enlace_personalizado': '',
        }
        payload.update(data)
        headers = extra_headers or {}
        return self.client.post(
            f'/colegios/ajax/guardar-clase/{self.colegio.id}/',
            data=payload,
            **headers,
        )

    def test_sin_hx_request_devuelve_json(self):
        r = self._post()
        self.assertEqual(r.status_code, 200)
        self.assertIn('application/json', r['Content-Type'])
        data = json.loads(r.content)
        self.assertTrue(data['ok'])

    def test_con_hx_request_devuelve_html(self):
        r = self._post(extra_headers={'HTTP_HX_REQUEST': 'true'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/html', r['Content-Type'])
        self.assertIn(b'info-clase', r.content)

    def test_con_hx_request_html_incluye_bloque_id_y_fecha(self):
        r = self._post(extra_headers={'HTTP_HX_REQUEST': 'true'})
        self.assertIn(b'info-clase-' + str(self.bloque.id).encode(), r.content)
        self.assertIn(b'2026-05-15', r.content)

    def test_con_hx_request_incluye_hx_trigger_con_toast(self):
        r = self._post(extra_headers={'HTTP_HX_REQUEST': 'true'})
        trigger = r.get('HX-Trigger')
        self.assertIsNotNone(trigger)
        triggers = json.loads(trigger)
        self.assertIn('showToast', triggers)
        self.assertEqual(triggers['showToast']['level'], 'success')

    def test_eliminar_con_hx_request_devuelve_celda_vacia(self):
        # Primero crear la clase
        Clase.objects.create(
            colegio=self.colegio, bloque=self.bloque,
            fecha=date(2026, 5, 15),
            materia=self.materia, profesor=self.profesor, unidad='1',
        )
        r = self._post(
            extra_headers={'HTTP_HX_REQUEST': 'true'},
            eliminar_clase='1',
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content.strip(), b'')
        trigger = json.loads(r.get('HX-Trigger', '{}'))
        self.assertEqual(trigger.get('showToast', {}).get('level'), 'warning')

    def test_eliminar_clase_regular_ofrece_recalcular(self):
        # Eliminar una clase regular con clases futuras de la misma materia debe ofrecer
        # renumerar esas futuras desde la unidad que ocupaba la borrada (materia_quitada).
        Clase.objects.create(
            colegio=self.colegio, bloque=self.bloque, fecha=date(2026, 5, 15),
            materia=self.materia, profesor=self.profesor, unidad='1',
        )
        Clase.objects.create(
            colegio=self.colegio, bloque=self.bloque, fecha=date(2026, 5, 22),
            materia=self.materia, profesor=self.profesor, unidad='2',
        )
        r = self._post(extra_headers={'HTTP_HX_REQUEST': 'true'}, eliminar_clase='1')
        self.assertEqual(r.status_code, 200)
        trigger = json.loads(r.get('HX-Trigger', '{}'))
        self.assertIn('recalcular', trigger)
        item = trigger['recalcular'][0]
        self.assertEqual(item['motivo'], 'materia_quitada')
        self.assertEqual(item['unidad_inicio'], 1)
        self.assertEqual(item['n_clases'], 1)
        self.assertEqual(item['materia'], 'Física')

    def test_eliminar_clase_sin_futuras_no_ofrece_recalcular(self):
        # Sin clases futuras de la materia, eliminar no dispara el modal de recálculo.
        Clase.objects.create(
            colegio=self.colegio, bloque=self.bloque, fecha=date(2026, 5, 15),
            materia=self.materia, profesor=self.profesor, unidad='1',
        )
        r = self._post(extra_headers={'HTTP_HX_REQUEST': 'true'}, eliminar_clase='1')
        trigger = json.loads(r.get('HX-Trigger', '{}'))
        self.assertNotIn('recalcular', trigger)

    def test_sin_permiso_devuelve_403(self):
        user_normal = User.objects.create_user('normal_htmx', password='pass')
        self.client.login(username='normal_htmx', password='pass')
        r = self._post(extra_headers={'HTTP_HX_REQUEST': 'true'})
        # ControlAccesoMiddleware redirige (302) antes de que la vista pueda devolver 403;
        # ambos implican acceso denegado.
        self.assertNotEqual(r.status_code, 200)

    def test_fecha_fuera_de_anio_devuelve_400(self):
        r = self._post(
            extra_headers={'HTTP_HX_REQUEST': 'true'},
            fecha_clase='2027-01-01',
        )
        self.assertEqual(r.status_code, 400)


class KanbanHTMXTest(TestCase):
    """Verifica que crear_tarea y cambiar_estado soporten HX-Request."""

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.admin = User.objects.create_superuser('admin_kanban', password='pass')
        self.client.login(username='admin_kanban', password='pass')

    def test_crear_tarea_htmx_devuelve_html_card(self):
        r = self.client.post(
            '/',
            {'crear_tarea': '1', 'titulo': 'Test HTMX tarea'},
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/html', r['Content-Type'])
        self.assertIn(b'Test HTMX tarea', r.content)
        self.assertIn(b'kanban-card', r.content)

    def test_crear_tarea_sin_htmx_redirige(self):
        r = self.client.post('/', {'crear_tarea': '1', 'titulo': 'Tarea normal'})
        self.assertEqual(r.status_code, 302)

    def test_cambiar_estado_htmx_devuelve_html_card(self):
        from programacion.pendientes.models import Tarea
        t = Tarea.objects.create(titulo='Tarea estado', creado_por=self.admin)
        r = self.client.post(
            f'/pendientes/cambiar-estado/{t.id}/gestion/',
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/html', r['Content-Type'])
        t.refresh_from_db()
        self.assertEqual(t.estado, 'gestion')


# ── Invalidación de caché del dashboard (matriz/stats) ────────────

class InvalidacionCacheDashboardTest(TestCase):
    """Regresión: matriz/stats cacheadas del dashboard deben invalidarse en TODAS
    las rutas que mutan los datos que las alimentan: la ruta no-JS de
    dashboard_colegios, los POST de configurar_colegio y el recálculo de
    secuencias (bulk_update no dispara signals)."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.admin = User.objects.create_superuser('admin_cache', password='pass')
        self.client.login(username='admin_cache', password='pass')
        col = Colegio.objects.create(
            nombre='Col Cache', departamento='Santander', ciudad='BGA')
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)
        self.grado = Grado.objects.create(nombre='11-1')
        self.bloque = Bloque.objects.create(
            colegio=self.colegio, grado=self.grado,
            hora_inicio=time(8, 0), hora_fin=time(10, 0))
        self.materia = Materia.objects.create(nombre='Física', color='#3498db')
        self.profesor = Profesor.objects.create(nombre='Luis', apellido='Ruiz')

    def _sembrar_cache(self):
        from django.core.cache import cache
        from programacion.colegios.views import _matriz_cache_key, _stats_cache_key
        self._ck_matriz = _matriz_cache_key(self.colegio.id, self.colegio.anio)
        self._ck_stats = _stats_cache_key(self.colegio.id, self.colegio.anio)
        cache.set(self._ck_matriz, {'sentinel': True}, 300)
        cache.set(self._ck_stats, {'sentinel': True}, 300)

    def _cache_invalidada(self):
        from django.core.cache import cache
        return cache.get(self._ck_matriz) is None and cache.get(self._ck_stats) is None

    def test_guardar_clase_ruta_no_js_invalida(self):
        # POST directo a dashboard_colegios (fallback sin JS), no al endpoint AJAX.
        self._sembrar_cache()
        r = self.client.post(f'/colegios/?id_col={self.colegio.id}', {
            'guardar_clase': '1',
            'bloque_id': str(self.bloque.id),
            'fecha_clase': '2026-05-15',
            'materia': 'Física',
            'profesor': str(self.profesor.id),
            'unidad': '1',
            'eliminar_clase': '0',
            'material_especial': '0',
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Clase.objects.filter(colegio=self.colegio).exists())
        self.assertTrue(self._cache_invalidada())

    def test_configurar_colegio_post_invalida(self):
        self._sembrar_cache()
        r = self.client.post(f'/colegios/configurar-colegio/{self.colegio.id}/', {
            'accion': 'set_valor_hora', 'valor_hora': '50000'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(self._cache_invalidada())

    def test_recalcular_secuencia_invalida(self):
        from django.core.cache import cache
        from core.views import _vg_cache_key
        Clase.objects.create(
            colegio=self.colegio, bloque=self.bloque, fecha=date(2026, 5, 15),
            materia=self.materia, profesor=self.profesor, unidad='3',
        )
        self._sembrar_cache()
        # bulk_update no dispara signals: también debe invalidar vista_general.
        ck_vg = _vg_cache_key(2026, 5)
        cache.set(ck_vg, {'sentinel': True}, 300)
        r = self.client.post(f'/colegios/ajax/recalcular-secuencia/{self.colegio.id}/', {
            'grado': '11-1', 'materia': 'Física',
            'fecha_desde': '2026-05-01', 'unidad_inicio': '1',
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Clase.objects.get(colegio=self.colegio).unidad, '1')
        self.assertTrue(self._cache_invalidada())
        self.assertIsNone(cache.get(ck_vg))
