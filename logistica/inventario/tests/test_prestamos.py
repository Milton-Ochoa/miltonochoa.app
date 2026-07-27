"""Tests de la Fase 5 (préstamos UI): gates, creación en ambas direcciones
(OTORGADO descuenta / RECIBIDO suma), devoluciones parciales y totales desde
el modal del detalle (operan sobre la bodega de cada línea), errores limpios
(stock insuficiente, sobre-devolución, préstamo cerrado) y snapshots.

Mismo arnés que tests_movimientos.py: `Client(HTTP_HOST='logistica.testserver')`.
"""
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import Client, TestCase
from django.utils import timezone

from core.areas import GRUPO_STAFF_FINANCIERA, GRUPO_STAFF_LOGISTICA

from logistica.inventario.models import (Bodega, Categoria, Devolucion, Item, Movimiento,
                     Prestamo, Stock, Tercero)
from logistica.inventario.services import crear_prestamo, registrar_entrada, registrar_salida
from logistica.inventario.tests.utils import crear_item


class _BasePrestamosTest(TestCase):
    """Cliente del subdominio + staff logueado + catálogo mínimo sembrado."""

    def setUp(self):
        self.client = Client(HTTP_HOST='logistica.testserver')
        self.user = User.objects.create_user(username='logis', password='pass')
        self.user.groups.add(Group.objects.get(name=GRUPO_STAFF_LOGISTICA))
        self.client.login(username='logis', password='pass')

        self.categoria = Categoria.objects.create(nombre='Papelería')
        self.bodega = Bodega.objects.create(nombre='Principal')
        self.bodega2 = Bodega.objects.create(nombre='Sucursal')
        self.item = crear_item(categoria=self.categoria, referencia='Resma carta')
        self.item2 = crear_item(categoria=self.categoria, referencia='Marcadores')
        self.tercero = Tercero.objects.create(nombre='Colegio Norte',
                                              documento='900123')
        self.manana = timezone.localdate() + timedelta(days=1)

    def _mensajes(self, response):
        return [str(m) for m in response.context['messages']]

    def _stock(self, item, bodega):
        fila = Stock.objects.filter(item=item, bodega=bodega).first()
        return fila.cantidad if fila else 0

    def _sembrar(self, item, bodega, cantidad):
        registrar_entrada(bodega=bodega, lineas=[(item, cantidad)],
                          usuario=self.user)

    def _prestamo_otorgado(self, lineas=None):
        return crear_prestamo(
            tercero=self.tercero, fecha_compromiso=self.manana,
            lineas=lineas or [(self.item, self.bodega, 5)], usuario=self.user)

    def _devolver(self, prestamo, pares, observaciones=''):
        """POST al modal de devolución; ``pares`` = [(PrestamoLinea, '<cant>')]."""
        return self.client.post(f'/prestamos/{prestamo.pk}/devolver/', {
            'dev_linea_id': [str(l.pk) for l, _ in pares],
            'dev_cantidad': [c for _, c in pares],
            'observaciones': observaciones,
        }, follow=True)


class GatesPrestamosTest(_BasePrestamosTest):

    def _urls(self):
        self._sembrar(self.item, self.bodega, 10)
        p = self._prestamo_otorgado()
        return ['/prestamos/', '/prestamos/nuevo/', f'/prestamos/{p.pk}/']

    def test_anonimo_redirigido(self):
        urls = self._urls()
        c = Client(HTTP_HOST='logistica.testserver')
        for url in urls:
            self.assertEqual(c.get(url).status_code, 302, url)

    def test_usuario_de_otra_area_no_entra(self):
        urls = self._urls()
        u = User.objects.create_user(username='finan', password='pass')
        u.groups.add(Group.objects.get(name=GRUPO_STAFF_FINANCIERA))
        c = Client(HTTP_HOST='logistica.testserver')
        c.login(username='finan', password='pass')
        for url in urls:
            self.assertEqual(c.get(url).status_code, 302, url)

    def test_staff_logistica_ve_todas_las_vistas(self):
        for url in self._urls():
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_devolver_exige_post(self):
        self._sembrar(self.item, self.bodega, 10)
        p = self._prestamo_otorgado()
        self.assertEqual(
            self.client.get(f'/prestamos/{p.pk}/devolver/').status_code, 405)


class CrearPrestamoUITest(_BasePrestamosTest):

    def test_otorgado_multilinea_multibodega_descuenta(self):
        self._sembrar(self.item, self.bodega, 10)
        self._sembrar(self.item2, self.bodega2, 8)
        r = self.client.post('/prestamos/nuevo/', {
            'direccion': 'OTORGADO', 'tercero': self.tercero.pk,
            'fecha_compromiso': self.manana.isoformat(), 'observaciones': '',
            'linea_item': [self.item.pk, self.item2.pk],
            'linea_bodega': [self.bodega.pk, self.bodega2.pk],
            'linea_cantidad': ['4', '3'],
        }, follow=True)
        prestamo = Prestamo.objects.get()
        self.assertEqual(prestamo.direccion, Prestamo.Direccion.OTORGADO)
        self.assertEqual(prestamo.estado, Prestamo.Estado.ABIERTO)
        self.assertEqual(prestamo.tercero_nombre, 'Colegio Norte')
        self.assertEqual(prestamo.tercero_documento, '900123')
        self.assertEqual(prestamo.lineas.count(), 2)
        self.assertEqual(self._stock(self.item, self.bodega), 6)
        self.assertEqual(self._stock(self.item2, self.bodega2), 5)
        movs = Movimiento.objects.filter(prestamo=prestamo)
        self.assertEqual(movs.count(), 2)
        self.assertTrue(all(m.tipo == Movimiento.Tipo.PRESTAMO for m in movs))
        # POST-redirect al detalle + toast
        self.assertEqual(r.request['PATH_INFO'], f'/prestamos/{prestamo.pk}/')
        self.assertTrue(any('registrado' in m for m in self._mensajes(r)))

    def test_otorgado_sin_stock_no_escribe_nada(self):
        self._sembrar(self.item, self.bodega, 2)
        r = self.client.post('/prestamos/nuevo/', {
            'direccion': 'OTORGADO', 'tercero': self.tercero.pk,
            'fecha_compromiso': self.manana.isoformat(),
            'linea_item': [self.item.pk], 'linea_bodega': [self.bodega.pk],
            'linea_cantidad': ['9'],
        })
        self.assertEqual(r.status_code, 200)  # re-render, no redirect
        self.assertFalse(Prestamo.objects.exists())
        self.assertEqual(self._stock(self.item, self.bodega), 2)
        self.assertTrue(any('Stock insuficiente' in m for m in self._mensajes(r)))

    def test_recibido_suma_stock_sin_validacion(self):
        # Nos prestan: no hace falta stock previo, el material ENTRA.
        self.client.post('/prestamos/nuevo/', {
            'direccion': 'RECIBIDO', 'tercero': self.tercero.pk,
            'fecha_compromiso': self.manana.isoformat(),
            'linea_item': [self.item.pk], 'linea_bodega': [self.bodega.pk],
            'linea_cantidad': ['6'],
        }, follow=True)
        prestamo = Prestamo.objects.get()
        self.assertEqual(prestamo.direccion, Prestamo.Direccion.RECIBIDO)
        self.assertEqual(self._stock(self.item, self.bodega), 6)
        mov = Movimiento.objects.get(prestamo=prestamo)
        self.assertEqual(mov.tipo, Movimiento.Tipo.PREST_RECIBIDO)

    def test_tercero_obligatorio(self):
        self._sembrar(self.item, self.bodega, 10)
        r = self.client.post('/prestamos/nuevo/', {
            'direccion': 'OTORGADO', 'tercero': '',
            'fecha_compromiso': self.manana.isoformat(),
            'linea_item': [self.item.pk], 'linea_bodega': [self.bodega.pk],
            'linea_cantidad': ['2'],
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Prestamo.objects.exists())
        self.assertTrue(self._mensajes(r))  # error legible del form

    def test_linea_sin_bodega_rechazada(self):
        self._sembrar(self.item, self.bodega, 10)
        r = self.client.post('/prestamos/nuevo/', {
            'direccion': 'OTORGADO', 'tercero': self.tercero.pk,
            'fecha_compromiso': self.manana.isoformat(),
            'linea_item': [self.item.pk], 'linea_bodega': [''],
            'linea_cantidad': ['2'],
        })
        self.assertFalse(Prestamo.objects.exists())
        self.assertTrue(any('sin bodega válida' in m for m in self._mensajes(r)))


class DevolucionUITest(_BasePrestamosTest):

    def test_devolucion_parcial_estado_parcial_y_bodega_de_linea(self):
        self._sembrar(self.item, self.bodega, 10)
        prestamo = self._prestamo_otorgado()  # presta 5 → quedan 5
        linea = prestamo.lineas.get()
        r = self._devolver(prestamo, [(linea, '2')], observaciones='Parcial')
        prestamo.refresh_from_db()
        linea.refresh_from_db()
        self.assertEqual(prestamo.estado, Prestamo.Estado.PARCIAL)
        self.assertIsNone(prestamo.cerrado_en)
        self.assertEqual(linea.cantidad_devuelta, 2)
        # Vuelve a la bodega de la línea (sin selector en la devolución).
        self.assertEqual(self._stock(self.item, self.bodega), 7)
        mov = Movimiento.objects.get(tipo=Movimiento.Tipo.DEVOLUCION)
        self.assertEqual(mov.bodega, self.bodega)
        self.assertTrue(any('Devolución' in m for m in self._mensajes(r)))

    def test_devolucion_total_cierra_prestamo(self):
        self._sembrar(self.item, self.bodega, 10)
        prestamo = self._prestamo_otorgado()
        linea = prestamo.lineas.get()
        self._devolver(prestamo, [(linea, '5')])
        prestamo.refresh_from_db()
        self.assertEqual(prestamo.estado, Prestamo.Estado.CERRADO)
        self.assertIsNotNone(prestamo.cerrado_en)
        self.assertEqual(self._stock(self.item, self.bodega), 10)

    def test_devolucion_solo_algunas_lineas(self):
        # Las filas en blanco/0 del modal se ignoran: parcial por línea.
        self._sembrar(self.item, self.bodega, 10)
        self._sembrar(self.item2, self.bodega2, 10)
        prestamo = self._prestamo_otorgado(
            [(self.item, self.bodega, 3), (self.item2, self.bodega2, 4)])
        l1, l2 = list(prestamo.lineas.order_by('pk'))
        self._devolver(prestamo, [(l1, ''), (l2, '4')])
        l1.refresh_from_db()
        l2.refresh_from_db()
        prestamo.refresh_from_db()
        self.assertEqual(l1.cantidad_devuelta, 0)
        self.assertEqual(l2.cantidad_devuelta, 4)
        self.assertEqual(prestamo.estado, Prestamo.Estado.PARCIAL)

    def test_devolucion_de_recibido_descuenta(self):
        prestamo = crear_prestamo(
            tercero=self.tercero, fecha_compromiso=self.manana,
            lineas=[(self.item, self.bodega, 6)], usuario=self.user,
            direccion=Prestamo.Direccion.RECIBIDO)
        self.assertEqual(self._stock(self.item, self.bodega), 6)
        linea = prestamo.lineas.get()
        self._devolver(prestamo, [(linea, '6')])
        prestamo.refresh_from_db()
        self.assertEqual(prestamo.estado, Prestamo.Estado.CERRADO)
        self.assertEqual(self._stock(self.item, self.bodega), 0)
        mov = Movimiento.objects.get(tipo=Movimiento.Tipo.DEV_RECIBIDO)
        self.assertEqual(mov.cantidad, 6)

    def test_devolucion_de_recibido_sin_stock_falla_limpio(self):
        # Nos prestaron 6 pero ya salieron 4 por otra vía: devolver 6 no alcanza.
        prestamo = crear_prestamo(
            tercero=self.tercero, fecha_compromiso=self.manana,
            lineas=[(self.item, self.bodega, 6)], usuario=self.user,
            direccion=Prestamo.Direccion.RECIBIDO)
        registrar_salida(bodega=self.bodega, lineas=[(self.item, 4)],
                         usuario=self.user)
        linea = prestamo.lineas.get()
        r = self._devolver(prestamo, [(linea, '6')])
        prestamo.refresh_from_db()
        linea.refresh_from_db()
        self.assertEqual(prestamo.estado, Prestamo.Estado.ABIERTO)
        self.assertEqual(linea.cantidad_devuelta, 0)
        self.assertEqual(self._stock(self.item, self.bodega), 2)
        self.assertFalse(Devolucion.objects.exists())
        self.assertTrue(any('Stock insuficiente' in m for m in self._mensajes(r)))

    def test_sobre_devolucion_rechazada(self):
        self._sembrar(self.item, self.bodega, 10)
        prestamo = self._prestamo_otorgado()  # presta 5
        linea = prestamo.lineas.get()
        r = self._devolver(prestamo, [(linea, '7')])
        linea.refresh_from_db()
        self.assertEqual(linea.cantidad_devuelta, 0)
        self.assertEqual(self._stock(self.item, self.bodega), 5)
        self.assertFalse(Devolucion.objects.exists())
        self.assertTrue(any('pendientes' in m for m in self._mensajes(r)))

    def test_todo_en_blanco_rechazado(self):
        self._sembrar(self.item, self.bodega, 10)
        prestamo = self._prestamo_otorgado()
        linea = prestamo.lineas.get()
        r = self._devolver(prestamo, [(linea, '')])
        self.assertFalse(Devolucion.objects.exists())
        self.assertTrue(any('al menos una línea' in m for m in self._mensajes(r)))

    def test_cantidad_no_numerica_rechazada(self):
        self._sembrar(self.item, self.bodega, 10)
        prestamo = self._prestamo_otorgado()
        linea = prestamo.lineas.get()
        r = self._devolver(prestamo, [(linea, 'abc')])
        self.assertFalse(Devolucion.objects.exists())
        self.assertTrue(any('inválida' in m for m in self._mensajes(r)))

    def test_cantidad_negativa_rechazada(self):
        self._sembrar(self.item, self.bodega, 10)
        prestamo = self._prestamo_otorgado()
        linea = prestamo.lineas.get()
        r = self._devolver(prestamo, [(linea, '-2')])
        self.assertFalse(Devolucion.objects.exists())
        self.assertTrue(any('mayor que cero' in m for m in self._mensajes(r)))

    def test_prestamo_cerrado_no_admite_devolver(self):
        self._sembrar(self.item, self.bodega, 10)
        prestamo = self._prestamo_otorgado()
        linea = prestamo.lineas.get()
        self._devolver(prestamo, [(linea, '5')])  # cierra
        r = self._devolver(prestamo, [(linea, '1')])
        self.assertEqual(Devolucion.objects.count(), 1)
        self.assertTrue(any('ya está cerrado' in m for m in self._mensajes(r)))

    def test_linea_de_otro_prestamo_rechazada(self):
        self._sembrar(self.item, self.bodega, 10)
        prestamo = self._prestamo_otorgado([(self.item, self.bodega, 2)])
        otro = self._prestamo_otorgado([(self.item, self.bodega, 3)])
        linea_ajena = otro.lineas.get()
        r = self._devolver(prestamo, [(linea_ajena, '1')])
        self.assertFalse(Devolucion.objects.exists())
        self.assertTrue(any('no pertenece' in m for m in self._mensajes(r)))


class ListaYDetalleTest(_BasePrestamosTest):

    def test_lista_marca_vencidos_en_ambas_direcciones(self):
        self._sembrar(self.item, self.bodega, 10)
        ayer = timezone.localdate() - timedelta(days=1)
        crear_prestamo(tercero=self.tercero, fecha_compromiso=ayer,
                       lineas=[(self.item, self.bodega, 1)], usuario=self.user)
        crear_prestamo(tercero=self.tercero, fecha_compromiso=ayer,
                       lineas=[(self.item2, self.bodega, 2)], usuario=self.user,
                       direccion=Prestamo.Direccion.RECIBIDO)
        r = self.client.get('/prestamos/')
        self.assertContains(r, 'Vencido', count=2)
        self.assertContains(r, 'Prestamos')   # badge OTORGADO
        self.assertContains(r, 'Nos prestan')  # badge RECIBIDO

    def test_lista_totales_prestado_y_pendiente(self):
        self._sembrar(self.item, self.bodega, 10)
        prestamo = self._prestamo_otorgado()  # 5 prestadas
        self._devolver(prestamo, [(prestamo.lineas.get(), '2')])
        r = self.client.get('/prestamos/')
        p = list(r.context['prestamos'])[0]
        self.assertEqual(p.prestado, 5)
        self.assertEqual(p.pendiente_total, 3)

    def test_detalle_muestra_lineas_y_devoluciones(self):
        self._sembrar(self.item, self.bodega, 10)
        prestamo = self._prestamo_otorgado()
        self._devolver(prestamo, [(prestamo.lineas.get(), '2')],
                       observaciones='Primera tanda')
        r = self.client.get(f'/prestamos/{prestamo.pk}/')
        self.assertContains(r, 'Resma carta')
        self.assertContains(r, 'Primera tanda')
        self.assertContains(r, 'Registrar devolución')  # modal disponible

    def test_detalle_cerrado_sin_boton_devolver(self):
        self._sembrar(self.item, self.bodega, 10)
        prestamo = self._prestamo_otorgado()
        self._devolver(prestamo, [(prestamo.lineas.get(), '5')])
        r = self.client.get(f'/prestamos/{prestamo.pk}/')
        self.assertNotContains(r, 'Registrar devolución')

    def test_snapshot_sobrevive_borrado_del_tercero(self):
        self._sembrar(self.item, self.bodega, 10)
        prestamo = self._prestamo_otorgado()
        self.tercero.delete()
        prestamo.refresh_from_db()
        self.assertIsNone(prestamo.tercero)
        self.assertEqual(prestamo.tercero_nombre, 'Colegio Norte')
        r = self.client.get(f'/prestamos/{prestamo.pk}/')
        self.assertContains(r, 'Colegio Norte')
        self.assertContains(r, 'snapshot')
