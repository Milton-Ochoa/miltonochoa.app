"""Tests de la Fase 3 (generación end-to-end): POST a `/personalizacion/generar/`
con una plantilla sembrada con fitz + un .xlsx en memoria, releyendo el PDF de la
respuesta con fitz para afirmar nº de páginas y contenido.

Mismo arnés de archivos que `tests_plantillas.py` (storage LOCAL en tmp →
NUNCA toca Supabase).
"""
import io
import shutil
import tempfile

import fitz
from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from core.areas import GRUPO_STAFF_LOGISTICA

from logistica.personalizacion.generar import campos_esperados
from logistica.personalizacion.models import PlantillaPersonalizacion
from .test_generar import _excel_bytes, crear_plantilla_bytes

_STORAGE_LOCAL = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
_MEDIA_TMP = tempfile.mkdtemp()


def _excel_upload(filas, encabezados=('Nombres', 'Grado', 'Usuario')):
    buf = _excel_bytes(filas, encabezados)
    return SimpleUploadedFile(
        'estudiantes.xlsx', buf.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@override_settings(MEDIA_ROOT=_MEDIA_TMP, STORAGES=_STORAGE_LOCAL)
class GenerarViewTest(TestCase):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_MEDIA_TMP, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.client = Client(HTTP_HOST='logistica.testserver')
        self.user = User.objects.create_user(username='logis', password='pass')
        self.user.groups.add(Group.objects.get(name=GRUPO_STAFF_LOGISTICA))
        self.client.login(username='logis', password='pass')

    def _crear_plantilla(self, tipo):
        pdf = SimpleUploadedFile(
            'plantilla.pdf', crear_plantilla_bytes(sorted(campos_esperados(tipo))),
            content_type='application/pdf')
        return PlantillaPersonalizacion.objects.create(
            nombre=f'Plantilla {tipo}', tipo=tipo, archivo=pdf, subido_por=self.user)

    def _mensajes(self, response):
        return [str(m) for m in response.context['messages']]

    def _pdf_de(self, response):
        contenido = b''.join(response.streaming_content)
        return fitz.open(stream=contenido, filetype='pdf')

    # ── Gate ──
    def test_get_muestra_formulario(self):
        r = self.client.get('/personalizacion/generar/')
        self.assertEqual(r.status_code, 200)
        # El select de plantilla lleva el buscador dinámico (Select2, patrón
        # inventario/_select2.html) para cuando haya muchas plantillas.
        self.assertContains(r, 'select2-busqueda')
        self.assertContains(r, 'select2.min.js')

    def test_no_logistica_redirigido(self):
        c = Client(HTTP_HOST='logistica.testserver')
        self.assertEqual(c.get('/personalizacion/generar/').status_code, 302)

    # ── SIMULACRO ──
    def test_simulacro_una_pagina_por_estudiante(self):
        plantilla = self._crear_plantilla('SIMULACRO')
        excel = _excel_upload([('Ana', 5, 'a'), ('Beto', 6, 'b'), ('Cami', 7, 'c')])
        r = self.client.post('/personalizacion/generar/', {
            'plantilla': plantilla.pk, 'colegio': 'Colegio X', 'excel': excel,
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertIn('attachment', r['Content-Disposition'])
        with self._pdf_de(r) as doc:
            self.assertEqual(doc.page_count, 3)

    # ── PENSAR (nº de prueba dividido en decena/unidad) ──
    def test_pensar_dos_por_hoja_con_numero_prueba(self):
        plantilla = self._crear_plantilla('PENSAR')
        excel = _excel_upload([('Ana', 5, 'a'), ('Beto', 5, 'b'),
                               ('Cami', 6, 'c'), ('Dani', 6, 'd')])
        r = self.client.post('/personalizacion/generar/', {
            'plantilla': plantilla.pk, 'colegio': 'Colegio Y',
            'numero_prueba': 42, 'excel': excel,
        })
        self.assertEqual(r.status_code, 200)
        with self._pdf_de(r) as doc:
            self.assertEqual(doc.page_count, 2)
            texto = doc[0].get_text()
        # decena=4, unidad=2 escritos en la hoja + el colegio.
        self.assertIn('4', texto)
        self.assertIn('2', texto)
        self.assertIn('Colegio Y', texto)

    def test_pensar_exige_numero_prueba(self):
        plantilla = self._crear_plantilla('PENSAR')
        excel = _excel_upload([('Ana', 5, 'a')])
        r = self.client.post('/personalizacion/generar/', {
            'plantilla': plantilla.pk, 'colegio': 'Colegio Y', 'excel': excel,
        }, follow=True)
        self.assertEqual(r.status_code, 200)  # re-render, no descarga
        self.assertTrue(any('número de prueba' in m.lower() for m in self._mensajes(r)))

    def test_simulacro_ignora_numero_prueba(self):
        # numero_prueba en SIMULACRO no es obligatorio ni afecta el resultado.
        plantilla = self._crear_plantilla('SIMULACRO')
        excel = _excel_upload([('Ana', 5, 'a')])
        r = self.client.post('/personalizacion/generar/', {
            'plantilla': plantilla.pk, 'colegio': 'Colegio X', 'excel': excel,
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')

    # ── Errores del Excel ──
    def test_excel_invalido_rerender(self):
        plantilla = self._crear_plantilla('SIMULACRO')
        malo = SimpleUploadedFile('malo.xlsx', b'no soy un xlsx',
                                  content_type='application/octet-stream')
        r = self.client.post('/personalizacion/generar/', {
            'plantilla': plantilla.pk, 'colegio': 'Colegio X', 'excel': malo,
        }, follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self._mensajes(r))  # algún toast de error

    def test_excel_sin_estudiantes_rerender(self):
        plantilla = self._crear_plantilla('SIMULACRO')
        excel = _excel_upload([('', 5, 'a'), (None, 6, 'b')])  # ninguna fila con nombre
        r = self.client.post('/personalizacion/generar/', {
            'plantilla': plantilla.pk, 'colegio': 'Colegio X', 'excel': excel,
        }, follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any('estudiantes' in m.lower() for m in self._mensajes(r)))
