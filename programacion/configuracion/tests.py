"""
Tests — app: configuracion
Modelos: Materia, NombreLibro, Unidad, Colegio, ColegioAnio, Profesor
"""
from datetime import date

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.db import IntegrityError
from programacion.configuracion.models import (
    Materia, NombreLibro, Unidad, Colegio, ColegioAnio, Profesor,
    periodo_por_defecto,
)


# ── NombreLibro ──────────────────────────────────────────────

class NombreLibroModelTest(TestCase):

    def setUp(self):
        self.libro = NombreLibro.objects.create(nombre='Saberes 11 Oro')

    def test_str_devuelve_nombre(self):
        self.assertEqual(str(self.libro), 'Saberes 11 Oro')

    def test_nombre_es_unico(self):
        with self.assertRaises(IntegrityError):
            NombreLibro.objects.create(nombre='Saberes 11 Oro')


# ── Unidad ───────────────────────────────────────────────────

class UnidadModelTest(TestCase):

    def setUp(self):
        self.libro = NombreLibro.objects.create(nombre='Saberes 11 Oro')
        self.materia = Materia.objects.create(nombre='Lectura Crítica')
        self.unidad = Unidad.objects.create(
            libro=self.libro, materia=self.materia,
            numero=1, nombre='Tú eliges cómo persuadir',
            link='https://example.com/u1',
        )

    def test_str_incluye_libro_materia_y_numero(self):
        r = str(self.unidad)
        self.assertIn('Saberes 11 Oro', r)
        self.assertIn('Lectura Crítica', r)
        self.assertIn('1', r)

    def test_mismo_libro_puede_tener_multiples_unidades(self):
        Unidad.objects.create(
            libro=self.libro, materia=self.materia,
            numero=2, nombre='Unidad dos',
            link='https://example.com/u2',
        )
        self.assertEqual(
            Unidad.objects.filter(libro=self.libro).count(), 2
        )

    def test_unique_together_libro_materia_numero(self):
        with self.assertRaises(IntegrityError):
            Unidad.objects.create(
                libro=self.libro, materia=self.materia,
                numero=1, nombre='Duplicada',
            )


# ── Colegio ───────────────────────────────────────────────────

class ColegioModelTest(TestCase):

    def setUp(self):
        self.colegio = Colegio.objects.create(
            nombre='Pablo Hoff', departamento='Bolívar', ciudad='Cartagena'
        )

    def test_str_incluye_nombre(self):
        self.assertIn('Pablo Hoff', str(self.colegio))

    def test_nombre_es_unico(self):
        with self.assertRaises(IntegrityError):
            Colegio.objects.create(nombre='Pablo Hoff', departamento='X', ciudad='Bogotá')

    def test_mapa_link_es_opcional(self):
        c = Colegio.objects.create(nombre='Sin Mapa', departamento='Antioquia', ciudad='Medellín')
        self.assertIsNone(c.mapa_link)

    def test_calendario_default_es_a(self):
        self.assertEqual(self.colegio.calendario, Colegio.Calendario.A)


# ── Calendario A/B y periodo (ColegioAnio) ───────────────────

class CalendarioPeriodoTest(TestCase):
    """Cubre el helper periodo_por_defecto, las propiedades de ColegioAnio
    (calendario/periodo_label/rango) y el autocálculo de fechas en save()."""

    def setUp(self):
        self.col_a = Colegio.objects.create(
            nombre='Colegio A', departamento='Santander', ciudad='Bucaramanga',
            calendario=Colegio.Calendario.A,
        )
        self.col_b = Colegio.objects.create(
            nombre='Colegio B', departamento='Santander', ciudad='Bucaramanga',
            calendario=Colegio.Calendario.B,
        )

    def test_periodo_por_defecto_calendario_a(self):
        inicio, fin = periodo_por_defecto(Colegio.Calendario.A, 2025)
        self.assertEqual(inicio, date(2025, 1, 1))
        self.assertEqual(fin, date(2025, 12, 31))

    def test_periodo_por_defecto_calendario_b_cruza_anio(self):
        inicio, fin = periodo_por_defecto(Colegio.Calendario.B, 2025)
        self.assertEqual(inicio, date(2025, 8, 1))
        self.assertEqual(fin, date(2026, 6, 30))

    def test_save_autocompleta_ventana_a(self):
        ca = ColegioAnio.objects.create(colegio=self.col_a, anio=2025)
        self.assertEqual(ca.fecha_inicio, date(2025, 1, 1))
        self.assertEqual(ca.fecha_fin, date(2025, 12, 31))

    def test_save_autocompleta_ventana_b(self):
        ca = ColegioAnio.objects.create(colegio=self.col_b, anio=2025)
        self.assertEqual(ca.fecha_inicio, date(2025, 8, 1))
        self.assertEqual(ca.fecha_fin, date(2026, 6, 30))

    def test_save_respeta_fechas_explicitas(self):
        ca = ColegioAnio.objects.create(
            colegio=self.col_b, anio=2025,
            fecha_inicio=date(2025, 9, 15), fecha_fin=date(2026, 6, 15),
        )
        self.assertEqual(ca.fecha_inicio, date(2025, 9, 15))
        self.assertEqual(ca.fecha_fin, date(2026, 6, 15))

    def test_periodo_label_a_es_anio(self):
        ca = ColegioAnio.objects.create(colegio=self.col_a, anio=2025)
        self.assertEqual(ca.periodo_label, '2025')

    def test_periodo_label_b_es_rango_cruzado(self):
        ca = ColegioAnio.objects.create(colegio=self.col_b, anio=2025)
        self.assertEqual(ca.periodo_label, '2025-2026')

    def test_rango_usa_fechas_guardadas(self):
        ca = ColegioAnio.objects.create(colegio=self.col_b, anio=2025)
        self.assertEqual(ca.rango, (date(2025, 8, 1), date(2026, 6, 30)))

    def test_calendario_proxy_delega_al_colegio(self):
        ca = ColegioAnio.objects.create(colegio=self.col_b, anio=2025)
        self.assertEqual(ca.calendario, Colegio.Calendario.B)

    def test_str_usa_periodo_label(self):
        ca = ColegioAnio.objects.create(colegio=self.col_b, anio=2025)
        self.assertIn('2025-2026', str(ca))


# ── Profesor ──────────────────────────────────────────────────

class ProfesorNombreCortoTest(TestCase):

    def test_nombre_y_apellido_simples(self):
        p = Profesor.objects.create(nombre='Adrianis', apellido='Mercado')
        self.assertEqual(p.nombre_corto, 'Adrianis Mercado')

    def test_nombre_compuesto_solo_toma_el_primero(self):
        p = Profesor.objects.create(nombre='Carlos Andrés', apellido='Rodríguez Pérez')
        self.assertEqual(p.nombre_corto, 'Carlos Rodríguez')

    def test_sin_apellido(self):
        p = Profesor.objects.create(nombre='Carlos')
        self.assertEqual(p.nombre_corto, 'Carlos')

    def test_str_devuelve_nombre_corto(self):
        p = Profesor.objects.create(nombre='Ana', apellido='García')
        self.assertEqual(str(p), p.nombre_corto)


class ProfesorCamposTest(TestCase):

    def test_campos_opcionales_son_nulos_por_defecto(self):
        p = Profesor.objects.create(nombre='Solo Nombre')
        self.assertIsNone(p.apellido)
        self.assertIsNone(p.documento)
        self.assertIsNone(p.email)
        self.assertIsNone(p.celular)
        self.assertIsNone(p.banco)

    def test_documento_unico(self):
        Profesor.objects.create(nombre='Juan', documento='12345678')
        with self.assertRaises(IntegrityError):
            Profesor.objects.create(nombre='Pedro', documento='12345678')

    def test_multiples_profesores_sin_documento_no_viola_unicidad(self):
        # NULL no cuenta como duplicado
        Profesor.objects.create(nombre='Prof A')
        Profesor.objects.create(nombre='Prof B')
        self.assertEqual(Profesor.objects.filter(documento=None).count(), 2)


# ── Vista configuracion_colegios: calendario A/B (Fase 2) ────────

class ConfiguracionColegiosCalendarioViewTest(TestCase):
    """La UI de configuración elige A/B al crear/editar y recomputa la ventana."""

    URL = '/configuracion/colegios/'

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        User.objects.create_superuser(username='admin_cfg', password='pass123')
        self.client.login(username='admin_cfg', password='pass123')

    def _datos_base(self, **extra):
        datos = {
            'accion':       'add',
            'nombre':       'Colegio Prueba',
            'codigo':       '',
            'departamento': 'Santander',
            'ciudad':       'Bucaramanga',
            'direccion':    '',
            'observacion':  '',
            'mapa_link':    '',
            'anio':         2025,
            'calendario':   Colegio.Calendario.A,
        }
        datos.update(extra)
        return datos

    def test_crear_colegio_b_genera_periodo_ago_jun(self):
        self.client.post(self.URL, self._datos_base(
            nombre='Colegio B', calendario=Colegio.Calendario.B, anio=2025))
        col = Colegio.objects.get(nombre='Colegio B')
        self.assertEqual(col.calendario, Colegio.Calendario.B)
        ca = col.anios.get(anio=2025)
        self.assertEqual(ca.fecha_inicio, date(2025, 8, 1))
        self.assertEqual(ca.fecha_fin, date(2026, 6, 30))
        self.assertEqual(ca.periodo_label, '2025-2026')

    def test_crear_colegio_a_genera_periodo_natural(self):
        self.client.post(self.URL, self._datos_base(
            nombre='Colegio A', calendario=Colegio.Calendario.A, anio=2025))
        ca = Colegio.objects.get(nombre='Colegio A').anios.get(anio=2025)
        self.assertEqual(ca.fecha_inicio, date(2025, 1, 1))
        self.assertEqual(ca.fecha_fin, date(2025, 12, 31))

    def test_editar_a_a_b_recomputa_periodos_sin_clases(self):
        # Colegio A con dos años; al pasarlo a B su ventana debe recalcularse.
        col = Colegio.objects.create(
            nombre='Colegio Mutante', departamento='Santander', ciudad='Bucaramanga')
        ColegioAnio.objects.create(colegio=col, anio=2025)
        ColegioAnio.objects.create(colegio=col, anio=2026)

        self.client.post(self.URL, self._datos_base(
            accion='edit', colegio_id=col.id, nombre='Colegio Mutante',
            calendario=Colegio.Calendario.B))

        col.refresh_from_db()
        self.assertEqual(col.calendario, Colegio.Calendario.B)
        ca25 = col.anios.get(anio=2025)
        self.assertEqual(ca25.fecha_inicio, date(2025, 8, 1))
        self.assertEqual(ca25.fecha_fin, date(2026, 6, 30))
        ca26 = col.anios.get(anio=2026)
        self.assertEqual(ca26.fecha_inicio, date(2026, 8, 1))
        self.assertEqual(ca26.fecha_fin, date(2027, 6, 30))

    def test_contexto_expone_calendario_y_periodo_label(self):
        col = Colegio.objects.create(
            nombre='Colegio Ctx', departamento='Santander', ciudad='Bucaramanga',
            calendario=Colegio.Calendario.B)
        ColegioAnio.objects.create(colegio=col, anio=2025)

        r = self.client.get(self.URL)
        self.assertEqual(r.status_code, 200)
        ctx_col = next(c for c in r.context['colegios'] if c.nombre == 'Colegio Ctx')
        self.assertEqual(ctx_col.calendario, Colegio.Calendario.B)
        self.assertEqual(ctx_col.todos_anios[0].periodo_label, '2025-2026')
        self.assertIn('2025-2026', ctx_col.anios_json)