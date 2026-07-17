"""Tests del servicio de importación (`logistica.despachos.services`).

Se fabrican los bytes de un reporte con `crear_reporte_bytes` y se importan con
`importar_reporte`, verificando upsert idempotente, refresco conservando marcas
locales, cierres automáticos, alertas, sync de líneas y contadores. Imports
absolutos (paquete `tests/`).
"""
import io

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from logistica.despachos.models import (ArticuloERP, CargaReporte, EventoOrden,
                                        LineaOrden, OrdenDespacho)
from logistica.despachos.reporte import crear_reporte_bytes
from logistica.despachos.services import ReporteViejo, importar_reporte

Estado = OrdenDespacho.Estado
Tipo = EventoOrden.Tipo


def _fila(**kw):
    """Fila de reporte mínima válida (una línea de una orden)."""
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


class _BaseImport(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='logis', password='x')

    def _importar(self, filas, **kw):
        datos = crear_reporte_bytes(filas, **kw)
        return importar_reporte(archivo=io.BytesIO(datos),
                                nombre_archivo='reporte.xls', usuario=self.user)


class CreacionInicialTest(_BaseImport):
    def test_crea_ordenes_lineas_catalogo(self):
        carga = self._importar([
            _fila(id_orden='PPAL-1', cod_articulo='727', descripcion='SIM-1', cantidad='17,00'),
            _fila(id_orden='PPAL-1', cod_articulo='728', descripcion='SIM-2', cantidad='3,00'),
            _fila(id_orden='PPAL-2', cod_articulo='999', descripcion='HORAS',
                  categoria='FORMACIÓN', cantidad='10,00'),
        ])
        self.assertEqual(OrdenDespacho.objects.count(), 2)
        self.assertEqual(LineaOrden.objects.count(), 3)
        self.assertEqual(ArticuloERP.objects.count(), 3)
        self.assertEqual(carga.n_nuevas, 2)
        self.assertEqual(carga.n_ordenes, 2)
        self.assertEqual(carga.n_filas, 3)
        self.assertEqual(carga.n_actualizadas, 0)

    def test_denormalizaciones_y_resumen(self):
        # El resumen usa la DESCRIPCIÓN del artículo (más legible que el código).
        self._importar([
            _fila(id_orden='PPAL-1', cod_articulo='727', descripcion='SIMULACRO 5', cantidad='17,00'),
            _fila(id_orden='PPAL-1', cod_articulo='728', descripcion='PENSAR 3', cantidad='3,00'),
        ])
        o = OrdenDespacho.objects.get(id_orden='PPAL-1')
        self.assertTrue(o.es_despachable)
        self.assertEqual(o.n_lineas, 2)
        self.assertEqual(o.resumen_articulos, '17× SIMULACRO 5; 3× PENSAR 3')

    def test_resumen_cae_al_codigo_si_no_hay_descripcion(self):
        # Sin descripción, el resumen usa el código como respaldo.
        self._importar([
            _fila(id_orden='PPAL-1', cod_articulo='727', descripcion='', cantidad='4,00'),
        ])
        o = OrdenDespacho.objects.get(id_orden='PPAL-1')
        self.assertEqual(o.resumen_articulos, '4× 727')

    def test_orden_100_formacion_no_es_despachable(self):
        self._importar([
            _fila(id_orden='PPAL-9', cod_articulo='H1', categoria='FORMACIÓN'),
        ])
        o = OrdenDespacho.objects.get(id_orden='PPAL-9')
        self.assertFalse(o.es_despachable)
        self.assertEqual(o.n_lineas, 0)
        self.assertEqual(o.resumen_articulos, '')
        # La línea FORMACIÓN igual se guarda (histórico), marcada no-material.
        self.assertEqual(o.lineas.count(), 1)
        self.assertFalse(o.lineas.first().es_material)

    def test_orden_mixta_solo_material_en_resumen(self):
        self._importar([
            _fila(id_orden='PPAL-1', cod_articulo='727', descripcion='SIMULACRO 5',
                  categoria='EVALUACIÓN', cantidad='5,00'),
            _fila(id_orden='PPAL-1', cod_articulo='H1', descripcion='HORAS CLASE',
                  categoria='FORMACIÓN', cantidad='2,00'),
        ])
        o = OrdenDespacho.objects.get(id_orden='PPAL-1')
        self.assertTrue(o.es_despachable)
        self.assertEqual(o.n_lineas, 1)
        self.assertEqual(o.resumen_articulos, '5× SIMULACRO 5')
        self.assertEqual(o.lineas.count(), 2)


class IdempotenciaTest(_BaseImport):
    def test_recarga_identica_sin_cambios(self):
        filas = [
            _fila(id_orden='PPAL-1', cod_articulo='727'),
            _fila(id_orden='PPAL-1', cod_articulo='728'),
            _fila(id_orden='PPAL-2', cod_articulo='999', categoria='FORMACIÓN'),
        ]
        self._importar(filas)
        carga2 = self._importar(filas)
        self.assertEqual(carga2.n_nuevas, 0)
        self.assertEqual(carga2.n_actualizadas, 0)
        self.assertEqual(OrdenDespacho.objects.count(), 2)
        self.assertEqual(LineaOrden.objects.count(), 3)
        self.assertEqual(EventoOrden.objects.count(), 0)


class RefrescoConservaMarcasTest(_BaseImport):
    def test_datos_erp_se_refrescan_pero_marca_local_intacta(self):
        self._importar([_fila(id_orden='PPAL-1', cliente='Colegio A')])
        o = OrdenDespacho.objects.get(id_orden='PPAL-1')
        o.estado = Estado.ALISTADA
        o.alistada_por = self.user
        o.alistada_en = timezone.now()
        o.save()

        carga2 = self._importar([_fila(id_orden='PPAL-1', cliente='Colegio B')])
        o.refresh_from_db()
        self.assertEqual(o.cliente, 'Colegio B')          # ERP refrescado
        self.assertEqual(o.estado, Estado.ALISTADA)        # marca local intacta
        self.assertEqual(o.alistada_por, self.user)
        self.assertEqual(carga2.n_actualizadas, 1)


class CierreAutomaticoTest(_BaseImport):
    def _anular(self, id_orden, facturacion):
        return self._importar([_fila(id_orden=id_orden, vigencia='Orden anulada',
                                     estado_facturacion=facturacion)])

    def test_anulada_con_remision_pasa_a_remitida_sin_marcar(self):
        self._importar([_fila(id_orden='PPAL-1')])  # vigente + pendiente
        self._anular('PPAL-1', 'Remisión de venta PPAL-5')
        o = OrdenDespacho.objects.get(id_orden='PPAL-1')
        self.assertEqual(o.estado, Estado.REMITIDA)
        self.assertTrue(o.cerrada_sin_marcar)
        self.assertIsNotNone(o.cerrada_en)
        self.assertTrue(o.eventos.filter(tipo=Tipo.CIERRE_SIN_MARCAR).exists())

    def test_anulada_pendiente_pasa_a_anulada(self):
        self._importar([_fila(id_orden='PPAL-1')])
        self._anular('PPAL-1', 'Pendiente')
        o = OrdenDespacho.objects.get(id_orden='PPAL-1')
        self.assertEqual(o.estado, Estado.ANULADA)
        self.assertTrue(o.cerrada_sin_marcar)

    def test_despachada_luego_remitida_es_cierre_auto_sin_marcar_false(self):
        self._importar([_fila(id_orden='PPAL-1')])
        o = OrdenDespacho.objects.get(id_orden='PPAL-1')
        o.estado = Estado.DESPACHADA
        o.despachada_por = self.user
        o.despachada_en = timezone.now()
        o.save()
        carga = self._anular('PPAL-1', 'Remisión de venta PPAL-1')
        o.refresh_from_db()
        self.assertEqual(o.estado, Estado.REMITIDA)
        self.assertFalse(o.cerrada_sin_marcar)
        self.assertTrue(o.eventos.filter(tipo=Tipo.CIERRE_AUTO).exists())
        self.assertEqual(carga.n_cerradas_auto, 1)

    def test_nueva_ya_anulada_sin_flag_ni_evento(self):
        carga = self._importar([
            _fila(id_orden='PPAL-9', vigencia='Orden anulada',
                  estado_facturacion='Remisión de venta PPAL-9')])
        o = OrdenDespacho.objects.get(id_orden='PPAL-9')
        self.assertEqual(o.estado, Estado.REMITIDA)
        self.assertFalse(o.cerrada_sin_marcar)
        self.assertIsNotNone(o.cerrada_en)
        self.assertEqual(o.eventos.count(), 0)
        self.assertEqual(carga.n_cerradas_auto, 0)

    def test_terminal_no_revive_en_recarga(self):
        self._importar([_fila(id_orden='PPAL-1')])
        self._anular('PPAL-1', 'Pendiente')  # → ANULADA
        # El ERP siempre trae la orden; recargar no debe generar más eventos.
        self._anular('PPAL-1', 'Pendiente')
        o = OrdenDespacho.objects.get(id_orden='PPAL-1')
        self.assertEqual(o.estado, Estado.ANULADA)
        self.assertEqual(o.eventos.filter(tipo=Tipo.CIERRE_SIN_MARCAR).count(), 1)


class AlertaRemisionTest(_BaseImport):
    def setUp(self):
        super().setUp()
        self._importar([_fila(id_orden='PPAL-1')])
        self.o = OrdenDespacho.objects.get(id_orden='PPAL-1')
        self.o.estado = Estado.DESPACHADA
        self.o.despachada_por = self.user
        self.o.despachada_en = timezone.now()
        self.o.save()

    def test_despachada_pero_erp_pendiente_alerta_y_evento_unico(self):
        c1 = self._importar([_fila(id_orden='PPAL-1')])  # sigue vigente+pendiente
        self.o.refresh_from_db()
        self.assertTrue(self.o.alerta_remision)
        self.assertEqual(self.o.estado, Estado.DESPACHADA)
        self.assertEqual(c1.n_alertas_remision, 1)
        self.assertEqual(self.o.eventos.filter(tipo=Tipo.ALERTA_REMISION).count(), 1)

        c2 = self._importar([_fila(id_orden='PPAL-1')])
        self.o.refresh_from_db()
        self.assertTrue(self.o.alerta_remision)
        self.assertEqual(c2.n_alertas_remision, 0)  # sin nuevo evento
        self.assertEqual(self.o.eventos.filter(tipo=Tipo.ALERTA_REMISION).count(), 1)

    def test_alerta_se_limpia_al_cerrar(self):
        self._importar([_fila(id_orden='PPAL-1')])  # levanta la alerta
        self._importar([_fila(id_orden='PPAL-1', vigencia='Orden anulada',
                              estado_facturacion='Remisión de venta PPAL-1')])
        self.o.refresh_from_db()
        self.assertFalse(self.o.alerta_remision)
        self.assertEqual(self.o.estado, Estado.REMITIDA)


class SyncLineasTest(_BaseImport):
    def test_linea_nueva_y_borrada(self):
        self._importar([
            _fila(id_orden='PPAL-1', cod_articulo='727'),
            _fila(id_orden='PPAL-1', cod_articulo='728'),
        ])
        self._importar([
            _fila(id_orden='PPAL-1', cod_articulo='727'),
            _fila(id_orden='PPAL-1', cod_articulo='999'),  # 728 fuera, 999 dentro
        ])
        o = OrdenDespacho.objects.get(id_orden='PPAL-1')
        cods = set(o.lineas.values_list('cod_articulo', flat=True))
        self.assertEqual(cods, {'727', '999'})
        self.assertEqual(o.lineas.count(), 2)

    def test_duplicados_por_ordinal(self):
        self._importar([
            _fila(id_orden='PPAL-1', cod_articulo='727', cantidad='5,00'),
            _fila(id_orden='PPAL-1', cod_articulo='727', cantidad='3,00'),
        ])
        self._importar([
            _fila(id_orden='PPAL-1', cod_articulo='727', cantidad='5,00'),
            _fila(id_orden='PPAL-1', cod_articulo='727', cantidad='10,00'),  # 2ª cambia
        ])
        o = OrdenDespacho.objects.get(id_orden='PPAL-1')
        cants = list(o.lineas.order_by('orden_archivo').values_list('cantidad', flat=True))
        self.assertEqual([str(c) for c in cants], ['5.00', '10.00'])
        self.assertEqual(o.lineas.count(), 2)

    def test_linea_con_cambio_material_no_se_borra_queda_huerfana(self):
        self._importar([_fila(id_orden='PPAL-1', cod_articulo='727')])
        o = OrdenDespacho.objects.get(id_orden='PPAL-1')
        linea = o.lineas.get(cod_articulo='727')
        sustituto = ArticuloERP.objects.create(codigo='SUB', descripcion='Reemplazo')
        linea.articulo_cambio = sustituto
        linea.cantidad_cambio = 1
        linea.cambiado_por = self.user
        linea.cambiado_en = timezone.now()
        linea.save()

        # El ERP quita la 727 y trae otra.
        self._importar([_fila(id_orden='PPAL-1', cod_articulo='999')])
        linea.refresh_from_db()
        self.assertTrue(linea.eliminada_erp)
        self.assertEqual(o.eventos.filter(tipo=Tipo.LINEA_HUERFANA).count(), 1)

        # Idempotente: recargar no re-emite el evento de huérfana.
        self._importar([_fila(id_orden='PPAL-1', cod_articulo='999')])
        self.assertEqual(o.eventos.filter(tipo=Tipo.LINEA_HUERFANA).count(), 1)


class CatalogoTest(_BaseImport):
    def test_upsert_refresca_descripcion(self):
        self._importar([_fila(cod_articulo='727', descripcion='SIM-A')])
        self.assertEqual(ArticuloERP.objects.get(codigo='727').descripcion, 'SIM-A')
        self._importar([_fila(cod_articulo='727', descripcion='SIM-B')])
        self.assertEqual(ArticuloERP.objects.count(), 1)
        self.assertEqual(ArticuloERP.objects.get(codigo='727').descripcion, 'SIM-B')

    def test_linea_referencia_articulo(self):
        self._importar([_fila(id_orden='PPAL-1', cod_articulo='727')])
        linea = LineaOrden.objects.get(cod_articulo='727')
        self.assertEqual(linea.articulo.codigo, '727')


class AntiViejoTest(_BaseImport):
    def test_archivo_mas_viejo_rechazado(self):
        self._importar([_fila(id_orden='PPAL-1', fecha_orden='2026-02-10 10:00:00')])
        with self.assertRaises(ReporteViejo):
            self._importar([_fila(id_orden='PPAL-2', fecha_orden='2026-01-01 09:00:00')])
        # No se aplicó nada del archivo viejo.
        self.assertFalse(OrdenDespacho.objects.filter(id_orden='PPAL-2').exists())

    def test_mismo_max_se_acepta(self):
        self._importar([_fila(id_orden='PPAL-1', fecha_orden='2026-02-10 10:00:00')])
        # Igual max = recarga del mismo día.
        self._importar([_fila(id_orden='PPAL-2', fecha_orden='2026-02-10 10:00:00')])
        self.assertTrue(OrdenDespacho.objects.filter(id_orden='PPAL-2').exists())
