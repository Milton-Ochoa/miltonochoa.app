"""Tests de la capa de servicio de personalización (Fase 1).

No tocan Django/ORM ni storage: prueban `generar_pdf`, `leer_estudiantes` y
`campos_faltantes` en unidad puro. Las plantillas se fabrican en memoria con el
propio fitz (no requieren PDFs reales).
"""
import io

import fitz
from django.test import SimpleTestCase
from openpyxl import Workbook

from logistica.personalizacion.excel import ExcelInvalido, leer_estudiantes
from logistica.personalizacion.generar import campos_esperados, generar_pdf
from logistica.personalizacion.validaciones import campos_faltantes


def crear_plantilla_bytes(campos):
    """PDF de una página con un widget de texto por cada nombre de campo."""
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for nombre in campos:
        w = fitz.Widget()
        w.field_name = nombre
        w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w.rect = fitz.Rect(72, y, 320, y + 18)
        page.add_widget(w)
        y += 28
    b = doc.tobytes()
    doc.close()
    return b


def _excel_bytes(filas, encabezados=('Nombres', 'Grado', 'Usuario')):
    """Construye un .xlsx en memoria y devuelve un file-like."""
    wb = Workbook()
    ws = wb.active
    ws.append(list(encabezados))
    for fila in filas:
        ws.append(list(fila))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _paginas(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype='pdf')
    try:
        return doc.page_count
    finally:
        doc.close()


def _texto_pagina(pdf_bytes, i):
    doc = fitz.open(stream=pdf_bytes, filetype='pdf')
    try:
        return doc[i].get_text()
    finally:
        doc.close()


class GenerarSimulacroTest(SimpleTestCase):
    def setUp(self):
        self.plantilla = crear_plantilla_bytes(sorted(campos_esperados('SIMULACRO')))

    def test_una_hoja_por_estudiante(self):
        estudiantes = [
            {'nombre': 'Ana Uno', 'grado': '5', 'usuario': 'ana1'},
            {'nombre': 'Beto Dos', 'grado': '6', 'usuario': 'beto2'},
            {'nombre': 'Cami Tres', 'grado': '7', 'usuario': 'cami3'},
        ]
        pdf = generar_pdf(plantilla_bytes=self.plantilla, tipo='SIMULACRO',
                          estudiantes=estudiantes, contexto={'colegio': 'COLE X'})
        self.assertEqual(_paginas(pdf), 3)

    def test_mismo_estudiante_arriba_y_abajo(self):
        estudiantes = [{'nombre': 'Ana Uno', 'grado': '5', 'usuario': 'ana1'}]
        pdf = generar_pdf(plantilla_bytes=self.plantilla, tipo='SIMULACRO',
                          estudiantes=estudiantes, contexto={'colegio': 'COLE X'})
        texto = _texto_pagina(pdf, 0)
        # El nombre aparece en ambas mitades (arriba y abajo) y el colegio también.
        self.assertEqual(texto.count('Ana Uno'), 2)
        self.assertIn('COLE X', texto)


class GenerarPensarTest(SimpleTestCase):
    def setUp(self):
        self.plantilla = crear_plantilla_bytes(sorted(campos_esperados('PENSAR')))
        self.ctx = {'colegio': 'COLE Y', 'decena': '4', 'unidad': '2'}

    def test_dos_estudiantes_por_hoja(self):
        estudiantes = [
            {'nombre': 'Ana', 'grado': '5', 'usuario': 'a'},
            {'nombre': 'Beto', 'grado': '5', 'usuario': 'b'},
            {'nombre': 'Cami', 'grado': '6', 'usuario': 'c'},
            {'nombre': 'Dani', 'grado': '6', 'usuario': 'd'},
        ]
        pdf = generar_pdf(plantilla_bytes=self.plantilla, tipo='PENSAR',
                          estudiantes=estudiantes, contexto=self.ctx)
        self.assertEqual(_paginas(pdf), 2)

    def test_impar_ultima_hoja_seccion_vacia(self):
        estudiantes = [
            {'nombre': 'Ana', 'grado': '5', 'usuario': 'a'},
            {'nombre': 'Beto', 'grado': '5', 'usuario': 'b'},
            {'nombre': 'Cami', 'grado': '6', 'usuario': 'c'},
        ]
        pdf = generar_pdf(plantilla_bytes=self.plantilla, tipo='PENSAR',
                          estudiantes=estudiantes, contexto=self.ctx)
        self.assertEqual(_paginas(pdf), 2)
        # La 2ª hoja lleva a Cami (arriba) pero no un 4º estudiante (abajo vacío).
        texto = _texto_pagina(pdf, 1)
        self.assertIn('Cami', texto)
        self.assertIn('COLE Y', texto)

    def test_numero_prueba_en_pdf(self):
        estudiantes = [{'nombre': 'Ana', 'grado': '5', 'usuario': 'a'}]
        pdf = generar_pdf(plantilla_bytes=self.plantilla, tipo='PENSAR',
                          estudiantes=estudiantes, contexto=self.ctx)
        texto = _texto_pagina(pdf, 0)
        # decena=4 y unidad=2 escritos en la hoja.
        self.assertIn('4', texto)
        self.assertIn('2', texto)


class CamposFaltantesTest(SimpleTestCase):
    def test_plantilla_completa_no_falta_nada(self):
        plantilla = crear_plantilla_bytes(sorted(campos_esperados('SIMULACRO')))
        self.assertEqual(campos_faltantes(plantilla, 'SIMULACRO'), [])

    def test_detecta_campos_faltantes(self):
        # Plantilla a la que le quitamos un campo esperado.
        campos = sorted(campos_esperados('SIMULACRO'))
        plantilla = crear_plantilla_bytes(campos[1:])  # falta el primero
        faltan = campos_faltantes(plantilla, 'SIMULACRO')
        self.assertEqual(faltan, [campos[0]])

    def test_pdf_sin_formulario_reporta_todos(self):
        doc = fitz.open()
        doc.new_page()
        plano = doc.tobytes()
        doc.close()
        self.assertEqual(set(campos_faltantes(plano, 'PENSAR')),
                         campos_esperados('PENSAR'))


class LeerEstudiantesTest(SimpleTestCase):
    def test_lectura_basica(self):
        excel = _excel_bytes([('Ana Uno', 5, 'ana1'), ('Beto Dos', 6, 'beto2')])
        est = leer_estudiantes(excel)
        self.assertEqual(len(est), 2)
        self.assertEqual(est[0], {'nombre': 'Ana Uno', 'grado': '5', 'usuario': 'ana1'})

    def test_encabezados_desordenados_y_mayusculas(self):
        excel = _excel_bytes([('a', 'Ana', '5')],
                             encabezados=('USUARIO', 'nombres', 'Grado'))
        est = leer_estudiantes(excel)
        self.assertEqual(est[0], {'nombre': 'Ana', 'grado': '5', 'usuario': 'a'})

    def test_fila_sin_nombre_se_omite(self):
        excel = _excel_bytes([('Ana', 5, 'a'), ('', 6, 'b'), (None, 7, 'c')])
        est = leer_estudiantes(excel)
        self.assertEqual(len(est), 1)
        self.assertEqual(est[0]['nombre'], 'Ana')

    def test_grado_float_se_limpia(self):
        # openpyxl puede leer 5 como 5.0; debe salir '5', no '5.0'.
        excel = _excel_bytes([('Ana', 5.0, 12.0)])
        est = leer_estudiantes(excel)
        self.assertEqual(est[0]['grado'], '5')
        self.assertEqual(est[0]['usuario'], '12')

    def test_columnas_faltantes_lanza(self):
        excel = _excel_bytes([('Ana', 5)], encabezados=('Nombres', 'Grado'))
        with self.assertRaises(ExcelInvalido):
            leer_estudiantes(excel)
