"""
Tests — app: configuracion
Modelos: Materia, NombreLibro, Unidad, Colegio, ColegioAnio, Profesor, DocumentoProfesor
"""
import shutil
import tempfile
from datetime import date

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from programacion.configuracion.models import (
    Materia, NombreLibro, Unidad, Colegio, ColegioAnio, Profesor,
    DocumentoProfesor, periodo_por_defecto,
)

# Almacenamiento local en tmp para los tests de documentos: NUNCA tocar Supabase.
_STORAGE_LOCAL = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
_MEDIA_TMP_DOCS = tempfile.mkdtemp()


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

# ── DocumentoProfesor (subida/listado/descarga/borrado) ──────

@override_settings(MEDIA_ROOT=_MEDIA_TMP_DOCS, STORAGES=_STORAGE_LOCAL)
class DocumentoProfesorTest(TestCase):
    """Adjuntos de la ficha del profesor: AJAX para subir/listar/borrar y proxy de descarga.

    Los archivos se fuerzan a disco (tmp) — nunca tocan Supabase. El gate es
    es_personal_programacion (superusuario o staff del área)."""

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.admin = User.objects.create_superuser('admin_doc', password='pass')
        self.profesor = Profesor.objects.create(nombre='Juan', apellido='Pérez', documento='123')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_MEDIA_TMP_DOCS, ignore_errors=True)
        super().tearDownClass()

    def _subir(self, nombre='cv.pdf', contenido=b'%PDF-1.4 datos', tipo='application/pdf'):
        return self.client.post(
            f'/configuracion/ajax/profesores/{self.profesor.id}/documentos/subir/',
            {'archivo': SimpleUploadedFile(nombre, contenido, content_type=tipo)},
        )

    def test_subir_crea_documento(self):
        self.client.login(username='admin_doc', password='pass')
        r = self._subir()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])
        self.assertEqual(self.profesor.documentos.count(), 1)
        doc = self.profesor.documentos.first()
        self.assertEqual(doc.nombre_original, 'cv.pdf')
        self.assertEqual(doc.subido_por, self.admin)

    def test_subir_rechaza_extension_no_permitida(self):
        self.client.login(username='admin_doc', password='pass')
        r = self._subir(nombre='virus.exe', contenido=b'MZ', tipo='application/octet-stream')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['ok'])
        self.assertEqual(self.profesor.documentos.count(), 0)

    def test_subir_acepta_office(self):
        self.client.login(username='admin_doc', password='pass')
        r = self._subir(nombre='hoja_vida.docx', contenido=b'PK\x03\x04',
                        tipo='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        self.assertTrue(r.json()['ok'])
        self.assertEqual(self.profesor.documentos.count(), 1)

    def test_listar_devuelve_documentos(self):
        self.client.login(username='admin_doc', password='pass')
        self._subir()
        r = self.client.get(f'/configuracion/ajax/profesores/{self.profesor.id}/documentos/')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data['ok'])
        self.assertEqual(len(data['documentos']), 1)
        self.assertEqual(data['documentos'][0]['nombre'], 'cv.pdf')

    def test_descarga_proxy_attachment_e_inline(self):
        self.client.login(username='admin_doc', password='pass')
        self._subir()
        doc = self.profesor.documentos.first()
        r = self.client.get(f'/configuracion/profesores/documentos/{doc.id}/descargar/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('attachment', r['Content-Disposition'])
        r2 = self.client.get(f'/configuracion/profesores/documentos/{doc.id}/descargar/?inline=1')
        self.assertIn('inline', r2['Content-Disposition'])

    def test_eliminar_borra_documento(self):
        self.client.login(username='admin_doc', password='pass')
        self._subir()
        doc = self.profesor.documentos.first()
        r = self.client.post(f'/configuracion/ajax/documentos/{doc.id}/eliminar/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])
        self.assertEqual(self.profesor.documentos.count(), 0)

    def test_sin_permiso_redirige(self):
        """Un usuario sin acceso al área (sin grupo ni superusuario) no puede subir."""
        User.objects.create_user('don_nadie', password='pass')
        self.client.login(username='don_nadie', password='pass')
        r = self._subir()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.profesor.documentos.count(), 0)


# ── Eliminación protegida (ProtectedError → error legible) ───────

class EliminacionProtegidaTest(TestCase):
    """Regresión: borrar entidades referenciadas por FKs PROTECT debe devolver un
    error legible (JSON o messages), nunca un 500 por ProtectedError sin manejar."""

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.user = User.objects.create_superuser(username='admin_prot', password='pass')
        self.client.login(username='admin_prot', password='pass')
        self.colegio = Colegio.objects.create(
            nombre='Col Protegido', departamento='Santander', ciudad='BGA')
        self.colegio_anio = ColegioAnio.objects.create(
            colegio=self.colegio, anio=2026, activo=True)
        self.profesor = Profesor.objects.create(nombre='Prote', apellido='Gido')

    def test_eliminar_libro_asignado_devuelve_error_legible(self):
        from programacion.colegios.models import Asignacion, Grado
        libro = NombreLibro.objects.create(nombre='Libro en uso')
        grado, _ = Grado.objects.get_or_create(nombre='11-1')
        Asignacion.objects.create(
            colegio=self.colegio_anio, grado=grado, libro=libro,
            fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 6, 30))
        r = self.client.post(f'/configuracion/ajax/libros/{libro.id}/eliminar/')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertFalse(data['ok'])
        self.assertIn('error', data)
        self.assertTrue(NombreLibro.objects.filter(id=libro.id).exists())

    def test_eliminar_colegio_con_pagos_devuelve_error_legible(self):
        from programacion.pagos.models import PagoRealizado
        PagoRealizado.objects.create(
            profesor=self.profesor, colegio=self.colegio_anio,
            fecha=date(2026, 3, 2), horas=2, valor=100000)
        r = self.client.post('/configuracion/colegios/', {
            'accion': 'del', 'colegio_id': self.colegio.id})
        self.assertEqual(r.status_code, 302)  # redirect, no 500
        self.assertTrue(Colegio.objects.filter(id=self.colegio.id).exists())

    def test_eliminar_profesor_con_viaticos_devuelve_error_legible(self):
        from programacion.viaticos.models import SolicitudViatico
        SolicitudViatico.objects.create(
            profesor=self.profesor, colegio=self.colegio,
            docente_nombre='Prote Gido', colegio_nombre=self.colegio.nombre,
            fecha_viaje=date(2026, 3, 2), fecha_regreso=date(2026, 3, 3),
            creado_por=self.user)
        r = self.client.post('/configuracion/profesores/', {
            'accion': 'del', 'profesor_id': self.profesor.id})
        self.assertEqual(r.status_code, 302)  # redirect, no 500
        self.assertTrue(Profesor.objects.filter(id=self.profesor.id).exists())

    def test_eliminar_profesor_protegido_no_deja_historial_espurio(self):
        from programacion.viaticos.models import SolicitudViatico
        from programacion.colegios.models import HistorialCambio
        SolicitudViatico.objects.create(
            profesor=self.profesor, colegio=self.colegio,
            docente_nombre='Prote Gido', colegio_nombre=self.colegio.nombre,
            fecha_viaje=date(2026, 3, 2), fecha_regreso=date(2026, 3, 3),
            creado_por=self.user)
        antes = HistorialCambio.objects.count()
        self.client.post('/configuracion/profesores/', {
            'accion': 'del', 'profesor_id': self.profesor.id})
        # El atomic revierte la entrada 'eliminar' si el delete falla por PROTECT
        self.assertEqual(HistorialCambio.objects.count(), antes)
