"""Tests del parser puro del reporte ERP (`logistica.despachos.reporte`).

Sin BD: se fabrican los bytes de un reporte con `crear_reporte_bytes` y se
verifica el `ReporteParseado`. Imports absolutos (paquete `tests/`).
"""
import io
from datetime import date, datetime
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase

from logistica.despachos import reporte
from logistica.despachos.reporte import (ReporteInvalido, crear_reporte_bytes,
                                         parsear_reporte)


def _fila(**kw):
    """Fila de reporte mínima válida; sobreescribe con kwargs."""
    base = {
        'sucursal': 'Principal', 'centro_costos': 'CC', 'bodega': 'BUCARAMANGA',
        'id_orden': 'PPAL-1', 'estado_orden_erp': 'Generada',
        'estado_facturacion': 'Pendiente', 'cliente': 'Colegio X',
        'id_cliente': 'CE 1', 'telefono': '3200000000', 'departamento': 'Santander',
        'ciudad': 'Bucaramanga', 'direccion': 'CALLE 1', 'categoria': 'EVALUACIÓN',
        'cod_articulo': '727', 'descripcion': 'SIM-GO1-11', 'cantidad': '17,00',
        'vendedor': 'Vendedor', 'observacion': 'obs', 'vigencia': 'Orden vigente',
        'fecha_entrega': '2026-01-28', 'fecha_orden': '2026-01-28 11:22:29',
    }
    base.update(kw)
    return base


def _parsear(filas, **kw):
    datos = crear_reporte_bytes(filas, **kw)
    return parsear_reporte(io.BytesIO(datos))


class ParserBasicoTest(SimpleTestCase):
    def test_una_fila_todos_los_campos(self):
        r = _parsear([_fila()])
        self.assertEqual(len(r.filas), 1)
        self.assertEqual(r.n_descartadas, 0)
        f = r.filas[0]
        self.assertEqual(f.id_orden, 'PPAL-1')
        self.assertEqual(f.bodega, 'BUCARAMANGA')
        self.assertEqual(f.categoria, 'EVALUACIÓN')
        self.assertEqual(f.cod_articulo, '727')
        self.assertEqual(f.cantidad, Decimal('17.00'))
        self.assertEqual(f.vigencia, 'Orden vigente')
        self.assertEqual(f.fecha_entrega, date(2026, 1, 28))
        self.assertEqual(f.fecha_orden, datetime(2026, 1, 28, 11, 22, 29))
        self.assertEqual(f.orden_archivo, 0)

    def test_varias_filas_orden_archivo_incremental(self):
        r = _parsear([_fila(id_orden='PPAL-1'), _fila(id_orden='PPAL-1'),
                      _fila(id_orden='PPAL-2')])
        self.assertEqual([f.orden_archivo for f in r.filas], [0, 1, 2])
        self.assertEqual({f.id_orden for f in r.filas}, {'PPAL-1', 'PPAL-2'})

    def test_reporte_vacio_sin_filas(self):
        r = _parsear([])
        self.assertEqual(r.filas, [])
        self.assertEqual(r.n_descartadas, 0)
        self.assertIsNone(r.max_fecha_orden)


class EncabezadosTest(SimpleTestCase):
    def test_orden_barajado(self):
        columnas = list(reporte._ORDEN_CAMPOS)
        columnas.reverse()  # encabezados y celdas en orden inverso
        r = _parsear([_fila()], columnas=columnas)
        f = r.filas[0]
        self.assertEqual(f.id_orden, 'PPAL-1')
        self.assertEqual(f.cantidad, Decimal('17.00'))
        self.assertEqual(f.fecha_entrega, date(2026, 1, 28))

    def test_mayusculas(self):
        labels = {'id_orden': 'ID ORDEN', 'cantidad': 'CANTIDAD',
                  'bodega': 'BODEGA'}
        r = _parsear([_fila()], labels=labels)
        self.assertEqual(r.filas[0].id_orden, 'PPAL-1')
        self.assertEqual(r.filas[0].bodega, 'BUCARAMANGA')

    def test_sin_tildes_en_encabezado(self):
        # El export podría venir sin acentos: 'Categoria articulo', 'Direccion'.
        labels = {'categoria': 'Categoria articulo', 'direccion': 'Direccion',
                  'descripcion': 'Descripcion original'}
        r = _parsear([_fila()], labels=labels)
        self.assertEqual(r.filas[0].categoria, 'EVALUACIÓN')
        self.assertEqual(r.filas[0].descripcion, 'SIM-GO1-11')

    def test_columna_obligatoria_faltante(self):
        columnas = [c for c in reporte._ORDEN_CAMPOS if c != 'id_orden']
        with self.assertRaises(ReporteInvalido) as ctx:
            _parsear([_fila()], columnas=columnas)
        self.assertIn('ID orden', str(ctx.exception))

    def test_columna_opcional_faltante_no_falla(self):
        # 'vendedor' no es obligatoria → se omite sin error, queda ''.
        columnas = [c for c in reporte._ORDEN_CAMPOS if c != 'vendedor']
        r = _parsear([_fila()], columnas=columnas)
        self.assertEqual(r.filas[0].vendedor, '')
        self.assertEqual(r.filas[0].id_orden, 'PPAL-1')

    def test_thead_sin_datos_valida_columnas(self):
        # Archivo con encabezados incompletos pero sin filas → igual falla.
        columnas = [c for c in reporte._ORDEN_CAMPOS if c != 'cantidad']
        with self.assertRaises(ReporteInvalido):
            _parsear([], columnas=columnas)


class EncodingYEntitiesTest(SimpleTestCase):
    def test_latin1_con_ene(self):
        r = _parsear([_fila(cliente='Colegio Muñoz', ciudad='Peñol')],
                     encoding='latin-1')
        self.assertEqual(r.filas[0].cliente, 'Colegio Muñoz')
        self.assertEqual(r.filas[0].ciudad, 'Peñol')

    def test_utf8_declarado(self):
        r = _parsear([_fila(cliente='Institución Ñandú')], encoding='utf-8')
        self.assertEqual(r.filas[0].cliente, 'Institución Ñandú')

    def test_entities_html(self):
        # convert_charrefs resuelve las entidades a su carácter.
        r = _parsear([_fila(cliente='Jos&eacute; &amp; Cia')])
        self.assertEqual(r.filas[0].cliente, 'José & Cia')

    def test_celda_con_tags_anidados(self):
        # Vigencia real viene como <b>Orden anulada</b>: el texto se limpia.
        r = _parsear([_fila(vigencia='<b>Orden anulada</b>')])
        self.assertEqual(r.filas[0].vigencia, 'Orden anulada')

    def test_espacios_colapsados(self):
        r = _parsear([_fila(direccion='CALLE 34   #  80B\n  - 37')])
        self.assertEqual(r.filas[0].direccion, 'CALLE 34 # 80B - 37')


class ConversionesTest(SimpleTestCase):
    def test_cantidad_coma_decimal(self):
        r = _parsear([_fila(cantidad='1.234,50')])
        self.assertEqual(r.filas[0].cantidad, Decimal('1234.50'))

    def test_cantidad_vacia_es_cero(self):
        r = _parsear([_fila(cantidad='')])
        self.assertEqual(r.filas[0].cantidad, Decimal('0'))

    def test_cantidad_invalida_es_cero(self):
        r = _parsear([_fila(cantidad='N/A')])
        self.assertEqual(r.filas[0].cantidad, Decimal('0'))

    def test_fecha_entrega_invalida_es_none(self):
        r = _parsear([_fila(fecha_entrega='0000-00-00')])
        self.assertIsNone(r.filas[0].fecha_entrega)

    def test_fecha_orden_vacia_es_none(self):
        r = _parsear([_fila(fecha_orden='')])
        self.assertIsNone(r.filas[0].fecha_orden)

    def test_fecha_orden_solo_fecha(self):
        r = _parsear([_fila(fecha_orden='2026-03-15')])
        self.assertEqual(r.filas[0].fecha_orden, datetime(2026, 3, 15, 0, 0, 0))


class DescartesYMaxFechaTest(SimpleTestCase):
    def test_fila_sin_id_orden_descartada(self):
        r = _parsear([_fila(id_orden=''), _fila(id_orden='PPAL-2')])
        self.assertEqual(len(r.filas), 1)
        self.assertEqual(r.n_descartadas, 1)
        self.assertEqual(r.filas[0].id_orden, 'PPAL-2')

    def test_fila_con_celdas_de_mas_descartada(self):
        # Inyecta una fila con una celda extra vía HTML crudo.
        datos = crear_reporte_bytes([_fila()])
        html = datos.decode('latin-1').replace(
            '</tbody>',
            '<tr><td>x</td></tr></tbody>')
        r = parsear_reporte(io.BytesIO(html.encode('latin-1')))
        self.assertEqual(len(r.filas), 1)
        self.assertEqual(r.n_descartadas, 1)

    def test_max_fecha_orden(self):
        r = _parsear([
            _fila(id_orden='PPAL-1', fecha_orden='2026-01-10 08:00:00'),
            _fila(id_orden='PPAL-2', fecha_orden='2026-05-20 15:30:00'),
            _fila(id_orden='PPAL-3', fecha_orden='2026-03-01 09:00:00'),
        ])
        self.assertEqual(r.max_fecha_orden, datetime(2026, 5, 20, 15, 30, 0))

    def test_max_fecha_ignora_none(self):
        r = _parsear([
            _fila(id_orden='PPAL-1', fecha_orden=''),
            _fila(id_orden='PPAL-2', fecha_orden='2026-02-02 10:00:00'),
        ])
        self.assertEqual(r.max_fecha_orden, datetime(2026, 2, 2, 10, 0, 0))


class ChunksTest(SimpleTestCase):
    def test_parseo_con_chunk_diminuto(self):
        # Un chunk de 8 bytes parte tags y celdas por la mitad: el feed
        # incremental debe reconstruirlos igual.
        filas = [_fila(id_orden=f'PPAL-{i}', cliente=f'Colegio {i} Ñ')
                 for i in range(1, 6)]
        datos = crear_reporte_bytes(filas)
        with mock.patch.object(reporte, '_CHUNK', 8):
            r = parsear_reporte(io.BytesIO(datos))
        self.assertEqual(len(r.filas), 5)
        self.assertEqual(r.n_descartadas, 0)
        self.assertEqual(r.filas[4].cliente, 'Colegio 5 Ñ')
