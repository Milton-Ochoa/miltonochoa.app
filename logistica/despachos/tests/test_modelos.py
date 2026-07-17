"""Tests de los modelos de despachos: defaults, properties, constraints y
tablas. Imports absolutos (paquete `tests/`)."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from logistica.despachos.models import (ArticuloERP, AsignacionBodega,
                                        CargaReporte, EventoOrden, LineaOrden,
                                        OrdenDespacho)


class TablasTest(TestCase):
    def test_db_table_prefijo_log(self):
        esperado = {
            OrdenDespacho: 'log_despachos_ordenes',
            LineaOrden: 'log_despachos_lineas',
            ArticuloERP: 'log_despachos_articulos',
            AsignacionBodega: 'log_despachos_bodegas_usuarios',
            EventoOrden: 'log_despachos_eventos',
            CargaReporte: 'log_despachos_cargas',
        }
        for modelo, tabla in esperado.items():
            self.assertEqual(modelo._meta.db_table, tabla)


class OrdenDespachoTest(TestCase):
    def test_defaults(self):
        o = OrdenDespacho.objects.create(id_orden='PPAL-1')
        self.assertEqual(o.estado, OrdenDespacho.Estado.PENDIENTE)
        self.assertTrue(o.es_despachable)
        self.assertFalse(o.alerta_remision)
        self.assertFalse(o.cerrada_sin_marcar)
        self.assertEqual(o.n_lineas, 0)
        self.assertEqual(o.resumen_articulos, '')

    def test_id_orden_unico(self):
        OrdenDespacho.objects.create(id_orden='PPAL-1')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OrdenDespacho.objects.create(id_orden='PPAL-1')

    def test_colegio_usa_centro_costos_con_fallback(self):
        # El colegio vive en 'Centro de costos'; si está vacío, cae al 'Cliente'.
        self.assertEqual(
            OrdenDespacho(centro_costos='COLEGIO REAL', cliente='Cli').colegio,
            'COLEGIO REAL')
        self.assertEqual(
            OrdenDespacho(centro_costos='', cliente='Colegio Fallback').colegio,
            'Colegio Fallback')

    def test_abierta(self):
        for estado, esperado in [
            (OrdenDespacho.Estado.PENDIENTE, True),
            (OrdenDespacho.Estado.ALISTADA, True),
            (OrdenDespacho.Estado.DESPACHADA, False),
            (OrdenDespacho.Estado.REMITIDA, False),
            (OrdenDespacho.Estado.ANULADA, False),
        ]:
            o = OrdenDespacho(id_orden='X', estado=estado)
            self.assertEqual(o.abierta, esperado, estado)

    def test_vencida_true(self):
        ayer = timezone.localdate() - timedelta(days=1)
        o = OrdenDespacho(id_orden='X', estado=OrdenDespacho.Estado.PENDIENTE,
                          es_despachable=True, fecha_entrega=ayer)
        self.assertTrue(o.vencida)

    def test_vencida_false_si_futura(self):
        manana = timezone.localdate() + timedelta(days=1)
        o = OrdenDespacho(id_orden='X', estado=OrdenDespacho.Estado.PENDIENTE,
                          es_despachable=True, fecha_entrega=manana)
        self.assertFalse(o.vencida)

    def test_vencida_false_si_no_despachable(self):
        ayer = timezone.localdate() - timedelta(days=1)
        o = OrdenDespacho(id_orden='X', estado=OrdenDespacho.Estado.PENDIENTE,
                          es_despachable=False, fecha_entrega=ayer)
        self.assertFalse(o.vencida)

    def test_vencida_false_si_cerrada(self):
        ayer = timezone.localdate() - timedelta(days=1)
        o = OrdenDespacho(id_orden='X', estado=OrdenDespacho.Estado.REMITIDA,
                          es_despachable=True, fecha_entrega=ayer)
        self.assertFalse(o.vencida)

    def test_vencida_false_sin_fecha(self):
        o = OrdenDespacho(id_orden='X', estado=OrdenDespacho.Estado.PENDIENTE,
                          es_despachable=True, fecha_entrega=None)
        self.assertFalse(o.vencida)


class LineaOrdenTest(TestCase):
    def setUp(self):
        self.orden = OrdenDespacho.objects.create(id_orden='PPAL-1')

    def test_defaults(self):
        linea = LineaOrden.objects.create(orden=self.orden, cod_articulo='727',
                                          cantidad=Decimal('3'))
        self.assertTrue(linea.es_material)
        self.assertFalse(linea.pendiente_erp)
        self.assertFalse(linea.eliminada_erp)
        self.assertFalse(linea.tiene_cambio)
        self.assertEqual(linea.orden_archivo, 0)

    def test_tiene_cambio(self):
        art = ArticuloERP.objects.create(codigo='999', descripcion='Reemplazo')
        linea = LineaOrden.objects.create(orden=self.orden, cod_articulo='727',
                                          articulo_cambio=art,
                                          cantidad_cambio=Decimal('2'))
        self.assertTrue(linea.tiene_cambio)

    def test_cascade_al_borrar_orden(self):
        LineaOrden.objects.create(orden=self.orden, cod_articulo='727')
        self.orden.delete()
        self.assertEqual(LineaOrden.objects.count(), 0)

    def test_articulo_cambio_protege(self):
        # PROTECT: no se puede borrar un ArticuloERP referido como cambio.
        art = ArticuloERP.objects.create(codigo='999')
        LineaOrden.objects.create(orden=self.orden, cod_articulo='727',
                                  articulo_cambio=art)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                art.delete()


class ArticuloERPTest(TestCase):
    def test_codigo_unico(self):
        ArticuloERP.objects.create(codigo='727')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ArticuloERP.objects.create(codigo='727')


class AsignacionBodegaTest(TestCase):
    def test_una_por_usuario(self):
        u = User.objects.create_user('u1')
        AsignacionBodega.objects.create(usuario=u, bodega='BUCARAMANGA')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AsignacionBodega.objects.create(usuario=u, bodega='MONTERIA')

    def test_borrar_usuario_borra_asignacion(self):
        u = User.objects.create_user('u2')
        AsignacionBodega.objects.create(usuario=u, bodega='BUCARAMANGA')
        u.delete()
        self.assertEqual(AsignacionBodega.objects.count(), 0)


class EventoOrdenTest(TestCase):
    def test_creacion_y_usuario_nulo(self):
        orden = OrdenDespacho.objects.create(id_orden='PPAL-1')
        # usuario None = evento automático del import.
        ev = EventoOrden.objects.create(orden=orden,
                                        tipo=EventoOrden.Tipo.CIERRE_AUTO,
                                        detalle='cierre')
        self.assertIsNone(ev.usuario)
        self.assertEqual(orden.eventos.count(), 1)

    def test_cascade_al_borrar_orden(self):
        orden = OrdenDespacho.objects.create(id_orden='PPAL-1')
        EventoOrden.objects.create(orden=orden, tipo=EventoOrden.Tipo.ALISTADA)
        orden.delete()
        self.assertEqual(EventoOrden.objects.count(), 0)

    def test_carga_set_null_al_borrar_carga(self):
        orden = OrdenDespacho.objects.create(id_orden='PPAL-1')
        carga = CargaReporte.objects.create(nombre_archivo='r.xls')
        ev = EventoOrden.objects.create(orden=orden,
                                        tipo=EventoOrden.Tipo.ALERTA_REMISION,
                                        carga=carga)
        carga.delete()
        ev.refresh_from_db()
        self.assertIsNone(ev.carga)


class CargaReporteTest(TestCase):
    def test_contadores_default_cero(self):
        c = CargaReporte.objects.create(nombre_archivo='r.xls')
        self.assertEqual(c.n_filas, 0)
        self.assertEqual(c.n_ordenes, 0)
        self.assertEqual(c.n_descartadas, 0)
        self.assertIsNone(c.max_fecha_orden)
