"""Tests de los servicios de dominio del inventario (sin vistas ni HTTP).

Corren en SQLite, donde `select_for_update` es no-op: aquí se prueba la
LÓGICA y la atomicidad (rollback total ante fallo); la exclusión concurrente
real solo existe en PostgreSQL (ver docstring de services.py).
"""
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from logistica.inventario.models import (Bodega, Categoria, Devolucion, DevolucionColegio, Entrada, Item, Movimiento,
                     Prestamo, PrestamoLinea, Salida, Stock, Tercero, Traslado)
from logistica.inventario.services import (ErrorDevolucion, StockInsuficiente, crear_prestamo,
                       items_bajo_minimo, kardex, prestamos_vencidos,
                       registrar_ajuste, registrar_devolucion,
                       registrar_devolucion_colegio, registrar_entrada,
                       registrar_salida, registrar_traslado)
from logistica.inventario.tests.utils import crear_item


class ServiciosBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('logi', password='x')
        cls.cat = Categoria.objects.create(nombre='Material académico')
        cls.bodega_a = Bodega.objects.create(nombre='Bodega A')
        cls.bodega_b = Bodega.objects.create(nombre='Bodega B')
        cls.item1 = crear_item(categoria=cls.cat, referencia='Libro guía',
                               grado=1)
        cls.item2 = crear_item(categoria=cls.cat, referencia='Resma carta',
                               grado=1,
                               unidad_medida=Item.UnidadMedida.RESMA)
        cls.tercero = Tercero.objects.create(nombre='Asesor Pérez',
                                             documento='123456')

    def _stock(self, item, bodega):
        fila = Stock.objects.filter(item=item, bodega=bodega).first()
        return fila.cantidad if fila else 0

    def _entrada(self, item, bodega, cantidad):
        return registrar_entrada(bodega=bodega, lineas=[(item, cantidad)],
                                 usuario=self.user)


class EntradaTests(ServiciosBase):
    def test_entrada_crea_documento_stock_y_kardex(self):
        entrada = registrar_entrada(bodega=self.bodega_a,
                                    lineas=[(self.item1, 10)],
                                    usuario=self.user, proveedor='Papelería X')
        self.assertEqual(entrada.lineas.count(), 1)
        self.assertEqual(self._stock(self.item1, self.bodega_a), 10)
        mov = Movimiento.objects.get()
        self.assertEqual(mov.tipo, Movimiento.Tipo.ENTRADA)
        self.assertEqual(mov.cantidad, 10)
        self.assertEqual(mov.saldo_resultante, 10)
        self.assertEqual(mov.entrada, entrada)
        self.assertEqual(mov.creado_por, self.user)
        self.assertIn('Papelería X', mov.detalle)
        self.assertEqual(mov.delta, 10)

    def test_entrada_multilinea(self):
        entrada = registrar_entrada(
            bodega=self.bodega_a,
            lineas=[(self.item1, 5), (self.item2, 7)], usuario=self.user)
        self.assertEqual(entrada.lineas.count(), 2)
        self.assertEqual(self._stock(self.item1, self.bodega_a), 5)
        self.assertEqual(self._stock(self.item2, self.bodega_a), 7)
        self.assertEqual(Movimiento.objects.count(), 2)

    def test_entrada_sin_lineas_falla(self):
        with self.assertRaises(ValueError):
            registrar_entrada(bodega=self.bodega_a, lineas=[],
                              usuario=self.user)
        self.assertEqual(Entrada.objects.count(), 0)

    def test_entrada_cantidad_cero_revierte_todo(self):
        with self.assertRaises(ValueError):
            registrar_entrada(bodega=self.bodega_a,
                              lineas=[(self.item1, 5), (self.item2, 0)],
                              usuario=self.user)
        self.assertEqual(Entrada.objects.count(), 0)
        self.assertEqual(Movimiento.objects.count(), 0)
        self.assertEqual(self._stock(self.item1, self.bodega_a), 0)


class SalidaTests(ServiciosBase):
    def test_salida_descuenta_stock(self):
        self._entrada(self.item1, self.bodega_a, 10)
        salida = registrar_salida(bodega=self.bodega_a,
                                  lineas=[(self.item1, 4)], usuario=self.user,
                                  motivo='Donación')
        self.assertEqual(self._stock(self.item1, self.bodega_a), 6)
        mov = Movimiento.objects.get(tipo=Movimiento.Tipo.SALIDA)
        self.assertEqual(mov.saldo_resultante, 6)
        self.assertEqual(mov.salida, salida)
        self.assertEqual(mov.delta, -4)

    def test_salida_snapshot_de_tercero_sobrevive_borrado(self):
        self._entrada(self.item1, self.bodega_a, 10)
        salida = registrar_salida(bodega=self.bodega_a,
                                  lineas=[(self.item1, 2)], usuario=self.user,
                                  tercero=self.tercero)
        self.assertEqual(salida.tercero_nombre, 'Asesor Pérez')
        Tercero.objects.filter(pk=self.tercero.pk).delete()
        salida.refresh_from_db()
        self.assertIsNone(salida.tercero)
        self.assertEqual(salida.tercero_nombre, 'Asesor Pérez')

    def test_salida_insuficiente_revierte_todo(self):
        # La línea 2 falla: ni el documento ni el movimiento de la línea 1
        # deben quedar escritos.
        self._entrada(self.item1, self.bodega_a, 10)
        with self.assertRaises(StockInsuficiente):
            registrar_salida(bodega=self.bodega_a,
                             lineas=[(self.item1, 5), (self.item2, 3)],
                             usuario=self.user)
        self.assertEqual(Salida.objects.count(), 0)
        self.assertFalse(
            Movimiento.objects.filter(tipo=Movimiento.Tipo.SALIDA).exists())
        self.assertEqual(self._stock(self.item1, self.bodega_a), 10)

    def test_salida_sin_fila_de_stock_reporta_disponible_cero(self):
        try:
            registrar_salida(bodega=self.bodega_a, lineas=[(self.item1, 1)],
                             usuario=self.user)
            self.fail('Debió lanzar StockInsuficiente')
        except StockInsuficiente as e:
            self.assertEqual(e.disponible, 0)
            self.assertEqual(e.solicitado, 1)


class TrasladoTests(ServiciosBase):
    def test_traslado_mueve_stock_entre_bodegas(self):
        self._entrada(self.item1, self.bodega_a, 10)
        traslado = registrar_traslado(bodega_origen=self.bodega_a,
                                      bodega_destino=self.bodega_b,
                                      lineas=[(self.item1, 4)],
                                      usuario=self.user)
        self.assertEqual(self._stock(self.item1, self.bodega_a), 6)
        self.assertEqual(self._stock(self.item1, self.bodega_b), 4)
        sal = Movimiento.objects.get(tipo=Movimiento.Tipo.TRASLADO_SAL)
        ent = Movimiento.objects.get(tipo=Movimiento.Tipo.TRASLADO_ENT)
        self.assertEqual((sal.bodega, sal.saldo_resultante), (self.bodega_a, 6))
        self.assertEqual((ent.bodega, ent.saldo_resultante), (self.bodega_b, 4))
        self.assertEqual(sal.traslado, traslado)
        self.assertEqual(ent.traslado, traslado)

    def test_traslado_misma_bodega_falla(self):
        with self.assertRaises(ValueError):
            registrar_traslado(bodega_origen=self.bodega_a,
                               bodega_destino=self.bodega_a,
                               lineas=[(self.item1, 1)], usuario=self.user)
        self.assertEqual(Traslado.objects.count(), 0)

    def test_traslado_insuficiente_revierte_todo(self):
        self._entrada(self.item1, self.bodega_a, 3)
        with self.assertRaises(StockInsuficiente):
            registrar_traslado(bodega_origen=self.bodega_a,
                               bodega_destino=self.bodega_b,
                               lineas=[(self.item1, 3), (self.item2, 1)],
                               usuario=self.user)
        self.assertEqual(Traslado.objects.count(), 0)
        self.assertEqual(self._stock(self.item1, self.bodega_a), 3)
        self.assertEqual(self._stock(self.item1, self.bodega_b), 0)


class PrestamoTests(ServiciosBase):
    def test_otorgado_descuenta_stock(self):
        self._entrada(self.item1, self.bodega_a, 10)
        prestamo = crear_prestamo(
            tercero=self.tercero, fecha_compromiso=date.today(),
            lineas=[(self.item1, self.bodega_a, 4)], usuario=self.user)
        self.assertEqual(prestamo.direccion, Prestamo.Direccion.OTORGADO)
        self.assertEqual(prestamo.estado, Prestamo.Estado.ABIERTO)
        self.assertEqual(self._stock(self.item1, self.bodega_a), 6)
        mov = Movimiento.objects.get(tipo=Movimiento.Tipo.PRESTAMO)
        self.assertEqual(mov.saldo_resultante, 6)
        self.assertEqual(mov.prestamo, prestamo)

    def test_otorgado_sin_stock_revierte_todo(self):
        self._entrada(self.item1, self.bodega_a, 2)
        with self.assertRaises(StockInsuficiente):
            crear_prestamo(tercero=self.tercero,
                           fecha_compromiso=date.today(),
                           lineas=[(self.item1, self.bodega_a, 5)],
                           usuario=self.user)
        self.assertEqual(Prestamo.objects.count(), 0)
        self.assertEqual(self._stock(self.item1, self.bodega_a), 2)

    def test_recibido_suma_stock_sin_validacion(self):
        # Nos prestan: entra material que no teníamos.
        prestamo = crear_prestamo(
            tercero=self.tercero, fecha_compromiso=date.today(),
            lineas=[(self.item1, self.bodega_a, 8)], usuario=self.user,
            direccion=Prestamo.Direccion.RECIBIDO)
        self.assertEqual(self._stock(self.item1, self.bodega_a), 8)
        mov = Movimiento.objects.get(tipo=Movimiento.Tipo.PREST_RECIBIDO)
        self.assertEqual(mov.saldo_resultante, 8)
        self.assertEqual(mov.delta, 8)
        self.assertEqual(prestamo.direccion, Prestamo.Direccion.RECIBIDO)

    def test_snapshot_de_tercero_sobrevive_borrado(self):
        self._entrada(self.item1, self.bodega_a, 5)
        prestamo = crear_prestamo(
            tercero=self.tercero, fecha_compromiso=date.today(),
            lineas=[(self.item1, self.bodega_a, 1)], usuario=self.user)
        Tercero.objects.filter(pk=self.tercero.pk).delete()
        prestamo.refresh_from_db()
        self.assertIsNone(prestamo.tercero)
        self.assertEqual(prestamo.tercero_nombre, 'Asesor Pérez')
        self.assertEqual(prestamo.tercero_documento, '123456')

    def test_otorgado_multibodega_descuenta_cada_bodega(self):
        self._entrada(self.item1, self.bodega_a, 5)
        self._entrada(self.item1, self.bodega_b, 5)
        crear_prestamo(tercero=self.tercero, fecha_compromiso=date.today(),
                       lineas=[(self.item1, self.bodega_a, 2),
                               (self.item1, self.bodega_b, 3)],
                       usuario=self.user)
        self.assertEqual(self._stock(self.item1, self.bodega_a), 3)
        self.assertEqual(self._stock(self.item1, self.bodega_b), 2)


class DevolucionTests(ServiciosBase):
    def _prestamo_otorgado(self, cantidad=10, stock_inicial=10):
        self._entrada(self.item1, self.bodega_a, stock_inicial)
        return crear_prestamo(tercero=self.tercero,
                              fecha_compromiso=date.today(),
                              lineas=[(self.item1, self.bodega_a, cantidad)],
                              usuario=self.user)

    def test_parcial_deja_estado_parcial(self):
        prestamo = self._prestamo_otorgado()
        linea = prestamo.lineas.get()
        registrar_devolucion(prestamo=prestamo, lineas=[(linea, 4)],
                             usuario=self.user)
        prestamo.refresh_from_db()
        linea.refresh_from_db()
        self.assertEqual(prestamo.estado, Prestamo.Estado.PARCIAL)
        self.assertIsNone(prestamo.cerrado_en)
        self.assertEqual(linea.cantidad_devuelta, 4)
        self.assertEqual(linea.pendiente, 6)
        # El material vuelve a la bodega de la línea.
        self.assertEqual(self._stock(self.item1, self.bodega_a), 4)

    def test_total_cierra_el_prestamo(self):
        prestamo = self._prestamo_otorgado()
        linea = prestamo.lineas.get()
        registrar_devolucion(prestamo=prestamo, lineas=[(linea, 10)],
                             usuario=self.user)
        prestamo.refresh_from_db()
        self.assertEqual(prestamo.estado, Prestamo.Estado.CERRADO)
        self.assertIsNotNone(prestamo.cerrado_en)
        self.assertEqual(self._stock(self.item1, self.bodega_a), 10)
        mov = Movimiento.objects.get(tipo=Movimiento.Tipo.DEVOLUCION)
        self.assertEqual(mov.saldo_resultante, 10)

    def test_devolucion_en_dos_actos_cierra_al_final(self):
        prestamo = self._prestamo_otorgado()
        linea = prestamo.lineas.get()
        registrar_devolucion(prestamo=prestamo, lineas=[(linea, 3)],
                             usuario=self.user)
        linea.refresh_from_db()
        prestamo.refresh_from_db()
        registrar_devolucion(prestamo=prestamo, lineas=[(linea, 7)],
                             usuario=self.user)
        prestamo.refresh_from_db()
        self.assertEqual(prestamo.estado, Prestamo.Estado.CERRADO)
        self.assertEqual(Devolucion.objects.count(), 2)

    def test_devolucion_de_recibido_descuenta(self):
        prestamo = crear_prestamo(
            tercero=self.tercero, fecha_compromiso=date.today(),
            lineas=[(self.item1, self.bodega_a, 8)], usuario=self.user,
            direccion=Prestamo.Direccion.RECIBIDO)
        linea = prestamo.lineas.get()
        registrar_devolucion(prestamo=prestamo, lineas=[(linea, 8)],
                             usuario=self.user)
        prestamo.refresh_from_db()
        self.assertEqual(prestamo.estado, Prestamo.Estado.CERRADO)
        self.assertEqual(self._stock(self.item1, self.bodega_a), 0)
        mov = Movimiento.objects.get(tipo=Movimiento.Tipo.DEV_RECIBIDO)
        self.assertEqual(mov.delta, -8)
        self.assertEqual(mov.saldo_resultante, 0)

    def test_devolucion_de_recibido_sin_stock_revierte(self):
        # Nos prestaron 5 pero ya salieron 4: devolver los 5 debe fallar
        # limpio, sin tocar stock ni estado.
        prestamo = crear_prestamo(
            tercero=self.tercero, fecha_compromiso=date.today(),
            lineas=[(self.item1, self.bodega_a, 5)], usuario=self.user,
            direccion=Prestamo.Direccion.RECIBIDO)
        registrar_salida(bodega=self.bodega_a, lineas=[(self.item1, 4)],
                         usuario=self.user)
        linea = prestamo.lineas.get()
        with self.assertRaises(StockInsuficiente):
            registrar_devolucion(prestamo=prestamo, lineas=[(linea, 5)],
                                 usuario=self.user)
        prestamo.refresh_from_db()
        linea.refresh_from_db()
        self.assertEqual(prestamo.estado, Prestamo.Estado.ABIERTO)
        self.assertEqual(linea.cantidad_devuelta, 0)
        self.assertEqual(self._stock(self.item1, self.bodega_a), 1)
        self.assertEqual(Devolucion.objects.count(), 0)

    def test_sobre_devolucion_rechazada(self):
        prestamo = self._prestamo_otorgado(cantidad=5)
        linea = prestamo.lineas.get()
        with self.assertRaises(ErrorDevolucion):
            registrar_devolucion(prestamo=prestamo, lineas=[(linea, 6)],
                                 usuario=self.user)
        self.assertEqual(Devolucion.objects.count(), 0)
        self.assertEqual(self._stock(self.item1, self.bodega_a), 5)

    def test_cantidad_cero_rechazada(self):
        prestamo = self._prestamo_otorgado()
        linea = prestamo.lineas.get()
        with self.assertRaises(ErrorDevolucion):
            registrar_devolucion(prestamo=prestamo, lineas=[(linea, 0)],
                                 usuario=self.user)

    def test_prestamo_cerrado_no_admite_devolver(self):
        prestamo = self._prestamo_otorgado(cantidad=2)
        linea = prestamo.lineas.get()
        registrar_devolucion(prestamo=prestamo, lineas=[(linea, 2)],
                             usuario=self.user)
        prestamo.refresh_from_db()
        linea.refresh_from_db()
        with self.assertRaises(ErrorDevolucion):
            registrar_devolucion(prestamo=prestamo, lineas=[(linea, 1)],
                                 usuario=self.user)

    def test_linea_de_otro_prestamo_rechazada(self):
        prestamo1 = self._prestamo_otorgado(cantidad=2, stock_inicial=10)
        prestamo2 = crear_prestamo(tercero=self.tercero,
                                   fecha_compromiso=date.today(),
                                   lineas=[(self.item1, self.bodega_a, 2)],
                                   usuario=self.user)
        linea_ajena = prestamo2.lineas.get()
        with self.assertRaises(ErrorDevolucion):
            registrar_devolucion(prestamo=prestamo1,
                                 lineas=[(linea_ajena, 1)],
                                 usuario=self.user)
        self.assertEqual(Devolucion.objects.count(), 0)


class AjusteTests(ServiciosBase):
    def test_ajuste_positivo(self):
        mov = registrar_ajuste(item=self.item1, bodega=self.bodega_a,
                               nueva_cantidad=15, usuario=self.user,
                               motivo='Conteo físico')
        self.assertEqual(mov.tipo, Movimiento.Tipo.AJUSTE_POS)
        self.assertEqual(mov.cantidad, 15)
        self.assertEqual(mov.saldo_resultante, 15)
        self.assertIn('Conteo físico', mov.detalle)
        self.assertEqual(self._stock(self.item1, self.bodega_a), 15)

    def test_ajuste_negativo(self):
        self._entrada(self.item1, self.bodega_a, 10)
        mov = registrar_ajuste(item=self.item1, bodega=self.bodega_a,
                               nueva_cantidad=4, usuario=self.user,
                               motivo='Material dañado')
        self.assertEqual(mov.tipo, Movimiento.Tipo.AJUSTE_NEG)
        self.assertEqual(mov.cantidad, 6)
        self.assertEqual(mov.saldo_resultante, 4)
        self.assertEqual(self._stock(self.item1, self.bodega_a), 4)

    def test_ajuste_sin_motivo_falla(self):
        with self.assertRaises(ValueError):
            registrar_ajuste(item=self.item1, bodega=self.bodega_a,
                             nueva_cantidad=5, usuario=self.user, motivo='  ')

    def test_ajuste_sin_delta_falla(self):
        self._entrada(self.item1, self.bodega_a, 5)
        with self.assertRaises(ValueError):
            registrar_ajuste(item=self.item1, bodega=self.bodega_a,
                             nueva_cantidad=5, usuario=self.user,
                             motivo='Nada cambió')

    def test_ajuste_negativo_absoluto_falla(self):
        with self.assertRaises(ValueError):
            registrar_ajuste(item=self.item1, bodega=self.bodega_a,
                             nueva_cantidad=-1, usuario=self.user,
                             motivo='Imposible')


class ConsultasTests(ServiciosBase):
    def test_kardex_mantiene_saldo_en_secuencia(self):
        registrar_entrada(bodega=self.bodega_a, lineas=[(self.item1, 10)],
                          usuario=self.user)
        registrar_salida(bodega=self.bodega_a, lineas=[(self.item1, 3)],
                         usuario=self.user)
        registrar_entrada(bodega=self.bodega_a, lineas=[(self.item1, 5)],
                          usuario=self.user)
        saldos = [m.saldo_resultante for m in kardex(self.item1)]
        self.assertEqual(saldos, [10, 7, 12])
        self.assertEqual(self._stock(self.item1, self.bodega_a), 12)

    def test_kardex_filtra_por_bodega(self):
        self._entrada(self.item1, self.bodega_a, 10)
        registrar_traslado(bodega_origen=self.bodega_a,
                           bodega_destino=self.bodega_b,
                           lineas=[(self.item1, 4)], usuario=self.user)
        movs_b = kardex(self.item1, bodega=self.bodega_b)
        self.assertEqual([m.tipo for m in movs_b],
                         [Movimiento.Tipo.TRASLADO_ENT])
        self.assertEqual(kardex(self.item1).count(), 3)

    def test_items_bajo_minimo(self):
        # item1: mínimo 5, stock total 3 (2 bodegas) → alerta.
        # item2: mínimo 5, stock 6 → sin alerta.
        # item3: mínimo 0 → nunca alerta, ni sin stock.
        self.item1.stock_minimo = 5
        self.item1.save()
        self.item2.stock_minimo = 5
        self.item2.save()
        item3 = crear_item(categoria=self.cat, referencia='Sin mínimo')
        self._entrada(self.item1, self.bodega_a, 1)
        self._entrada(self.item1, self.bodega_b, 2)
        self._entrada(self.item2, self.bodega_a, 6)
        bajos = list(items_bajo_minimo())
        self.assertIn(self.item1, bajos)
        self.assertNotIn(self.item2, bajos)
        self.assertNotIn(item3, bajos)
        self.assertEqual(bajos[0].stock_total, 3)

    def test_item_con_minimo_y_sin_stock_alerta(self):
        self.item1.stock_minimo = 2
        self.item1.save()
        self.assertIn(self.item1, list(items_bajo_minimo()))

    def test_prestamos_vencidos_en_ambas_direcciones(self):
        self._entrada(self.item1, self.bodega_a, 10)
        ayer = date.today() - timedelta(days=1)
        manana = date.today() + timedelta(days=1)
        vencido_otorgado = crear_prestamo(
            tercero=self.tercero, fecha_compromiso=ayer,
            lineas=[(self.item1, self.bodega_a, 1)], usuario=self.user)
        vencido_recibido = crear_prestamo(
            tercero=self.tercero, fecha_compromiso=ayer,
            lineas=[(self.item1, self.bodega_a, 1)], usuario=self.user,
            direccion=Prestamo.Direccion.RECIBIDO)
        al_dia = crear_prestamo(
            tercero=self.tercero, fecha_compromiso=manana,
            lineas=[(self.item1, self.bodega_a, 1)], usuario=self.user)
        cerrado = crear_prestamo(
            tercero=self.tercero, fecha_compromiso=ayer,
            lineas=[(self.item1, self.bodega_a, 1)], usuario=self.user)
        registrar_devolucion(prestamo=cerrado,
                             lineas=[(cerrado.lineas.get(), 1)],
                             usuario=self.user)
        vencidos = list(prestamos_vencidos())
        self.assertIn(vencido_otorgado, vencidos)
        self.assertIn(vencido_recibido, vencidos)
        self.assertNotIn(al_dia, vencidos)
        self.assertNotIn(cerrado, vencidos)
        self.assertTrue(vencido_otorgado.vencido)
        self.assertFalse(al_dia.vencido)
        cerrado.refresh_from_db()
        self.assertFalse(cerrado.vencido)


class DevolucionColegioTests(ServiciosBase):
    """Material que un colegio devuelve sin usar: suma stock con rastro."""

    def _devolver(self, lineas, **kw):
        datos = {'fecha_recibido': date(2026, 7, 20), 'colegio': 'Colegio Norte'}
        datos.update(kw)
        return registrar_devolucion_colegio(bodega=self.bodega_a, lineas=lineas,
                                            usuario=self.user, **datos)

    def test_suma_stock_y_asienta_kardex(self):
        dev = self._devolver([(self.item1, 6)], codigo_colegio='C-01',
                             regional='Norte', ejecutivo='Ana Ruiz')
        self.assertEqual(self._stock(self.item1, self.bodega_a), 6)
        self.assertEqual(dev.lineas.count(), 1)
        mov = Movimiento.objects.get()
        self.assertEqual(mov.tipo, Movimiento.Tipo.DEV_COLEGIO)
        self.assertEqual(mov.delta, 6)  # el tipo debe sumar
        self.assertEqual(mov.saldo_resultante, 6)
        self.assertEqual(mov.devolucion_colegio, dev)
        self.assertIn('Colegio Norte', mov.detalle)
        self.assertEqual(dev.regional, 'Norte')
        self.assertEqual(dev.ejecutivo, 'Ana Ruiz')

    def test_suma_sobre_lo_que_ya_habia(self):
        self._entrada(self.item1, self.bodega_a, 4)
        self._devolver([(self.item1, 3)])
        self.assertEqual(self._stock(self.item1, self.bodega_a), 7)

    def test_multilinea_un_movimiento_por_item(self):
        dev = self._devolver([(self.item1, 2), (self.item2, 5)])
        self.assertEqual(dev.lineas.count(), 2)
        self.assertEqual(
            Movimiento.objects.filter(devolucion_colegio=dev).count(), 2)

    def test_cantidad_invalida_revierte_todo(self):
        with self.assertRaises(ValueError):
            self._devolver([(self.item1, 3), (self.item2, 0)])
        # Ni documento ni la línea buena: el atomic revierte completo.
        self.assertEqual(DevolucionColegio.objects.count(), 0)
        self.assertEqual(Movimiento.objects.count(), 0)
        self.assertEqual(self._stock(self.item1, self.bodega_a), 0)

    def test_sin_lineas_rechazada(self):
        with self.assertRaises(ValueError):
            self._devolver([])

    def test_no_se_puede_borrar_si_movio_stock(self):
        dev = self._devolver([(self.item1, 1)])
        with self.assertRaises(ProtectedError):
            with transaction.atomic():
                dev.delete()

    def test_kardex_incluye_la_devolucion(self):
        self._devolver([(self.item1, 2)])
        tipos = [m.tipo for m in kardex(self.item1)]
        self.assertEqual(tipos, [Movimiento.Tipo.DEV_COLEGIO])


class ConstraintTests(ServiciosBase):
    def test_material_por_grado_unico(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                crear_item(categoria=self.cat, referencia='Libro guía', grado=1)

    def test_mismo_material_en_otro_grado_convive(self):
        otro = crear_item(categoria=self.cat, referencia='Libro guía', grado=2)
        self.assertEqual(otro.nombre, 'Material académico Libro guía — 2°')

    def test_grado_fuera_de_rango_rechazado(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                crear_item(categoria=self.cat, referencia='Fuera', grado=12)

    def test_documento_de_tercero_unico_solo_si_diligenciado(self):
        # Dos terceros sin documento conviven; documento repetido no.
        Tercero.objects.create(nombre='Sin doc 1')
        Tercero.objects.create(nombre='Sin doc 2')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Tercero.objects.create(nombre='Clon', documento='123456')

    def test_stock_unico_por_item_bodega(self):
        Stock.objects.create(item=self.item1, bodega=self.bodega_a, cantidad=1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Stock.objects.create(item=self.item1, bodega=self.bodega_a,
                                     cantidad=2)

    def test_traslado_bodegas_distintas_en_bd(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Traslado.objects.create(bodega_origen=self.bodega_a,
                                        bodega_destino=self.bodega_a)

    def test_devuelta_no_supera_prestada_en_bd(self):
        self._entrada(self.item1, self.bodega_a, 5)
        prestamo = crear_prestamo(tercero=self.tercero,
                                  fecha_compromiso=date.today(),
                                  lineas=[(self.item1, self.bodega_a, 2)],
                                  usuario=self.user)
        linea = prestamo.lineas.get()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PrestamoLinea.objects.filter(pk=linea.pk).update(
                    cantidad_devuelta=3)
