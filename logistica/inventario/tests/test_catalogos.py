"""Tests de la Fase 3 (catálogos UI): gates de acceso, CRUDs de artículos /
bodegas / categorías / terceros, guard del soft-delete de bodega, alta AJAX de
tercero y la vista de existencias con datos sembrados por los servicios.

Mismo arnés que tests_area.py: `Client(HTTP_HOST='logistica.testserver')`.
El stock de los tests se siembra SIEMPRE vía services (única puerta de
escritura), nunca tocando `Stock` directo.
"""
from django.contrib.auth.models import Group, User
from django.test import Client, TestCase

from core.areas import GRUPO_STAFF_FINANCIERA, GRUPO_STAFF_LOGISTICA

from logistica.inventario.models import Bodega, Categoria, Item, Stock, Tercero
from logistica.inventario.services import registrar_entrada, registrar_salida


class _BaseCatalogosTest(TestCase):
    """Cliente del subdominio + usuario staff de logística ya logueado."""

    def setUp(self):
        self.client = Client(HTTP_HOST='logistica.testserver')
        self.user = User.objects.create_user(username='logis', password='pass')
        self.user.groups.add(Group.objects.get(name=GRUPO_STAFF_LOGISTICA))
        self.client.login(username='logis', password='pass')

    def _mensajes(self, response):
        return [str(m) for m in response.context['messages']]


class GatesCatalogosTest(TestCase):

    URLS = ['/articulos/', '/catalogos/bodegas/', '/catalogos/categorias/',
            '/terceros/', '/stock/']

    def test_anonimo_redirigido_en_todas_las_vistas(self):
        c = Client(HTTP_HOST='logistica.testserver')
        for url in self.URLS:
            r = c.get(url)
            self.assertEqual(r.status_code, 302, url)

    def test_usuario_de_otra_area_no_entra(self):
        u = User.objects.create_user(username='finan', password='pass')
        u.groups.add(Group.objects.get(name=GRUPO_STAFF_FINANCIERA))
        c = Client(HTTP_HOST='logistica.testserver')
        c.login(username='finan', password='pass')
        for url in self.URLS:
            r = c.get(url)
            self.assertEqual(r.status_code, 302, url)

    def test_staff_logistica_ve_todas_las_vistas(self):
        u = User.objects.create_user(username='logis', password='pass')
        u.groups.add(Group.objects.get(name=GRUPO_STAFF_LOGISTICA))
        c = Client(HTTP_HOST='logistica.testserver')
        c.login(username='logis', password='pass')
        for url in self.URLS:
            r = c.get(url)
            self.assertEqual(r.status_code, 200, url)


class CategoriasTest(_BaseCatalogosTest):

    def test_crear_categoria(self):
        r = self.client.post('/catalogos/categorias/', {'nombre': 'Papelería'},
                             follow=True)
        self.assertTrue(Categoria.objects.filter(nombre='Papelería').exists())
        self.assertTrue(any('creada' in m for m in self._mensajes(r)))

    def test_editar_categoria(self):
        cat = Categoria.objects.create(nombre='Papeleria')
        self.client.post('/catalogos/categorias/',
                         {'categoria_id': cat.pk, 'nombre': 'Papelería'})
        cat.refresh_from_db()
        self.assertEqual(cat.nombre, 'Papelería')

    def test_nombre_duplicado_no_crea(self):
        Categoria.objects.create(nombre='Papelería')
        r = self.client.post('/catalogos/categorias/', {'nombre': 'Papelería'},
                             follow=True)
        self.assertEqual(Categoria.objects.count(), 1)
        self.assertTrue(self._mensajes(r))  # hubo error legible

    def test_eliminar_categoria_sin_items(self):
        cat = Categoria.objects.create(nombre='Temporal')
        self.client.post('/catalogos/categorias/',
                         {'accion': 'eliminar', 'categoria_id': cat.pk})
        self.assertFalse(Categoria.objects.filter(pk=cat.pk).exists())

    def test_eliminar_categoria_con_items_protegida(self):
        cat = Categoria.objects.create(nombre='Con items')
        Item.objects.create(codigo='X1', nombre='Algo', categoria=cat)
        r = self.client.post('/catalogos/categorias/',
                             {'accion': 'eliminar', 'categoria_id': cat.pk},
                             follow=True)
        self.assertTrue(Categoria.objects.filter(pk=cat.pk).exists())
        self.assertTrue(any('No se puede eliminar' in m for m in self._mensajes(r)))


class BodegasTest(_BaseCatalogosTest):

    def test_crear_y_editar_bodega(self):
        self.client.post('/catalogos/bodegas/', {'nombre': 'Principal'})
        bodega = Bodega.objects.get(nombre='Principal')
        self.client.post('/catalogos/bodegas/',
                         {'bodega_id': bodega.pk, 'nombre': 'Principal',
                          'ubicacion': 'Sede norte'})
        bodega.refresh_from_db()
        self.assertEqual(bodega.ubicacion, 'Sede norte')

    def test_desactivar_bodega_sin_stock(self):
        bodega = Bodega.objects.create(nombre='Vacía')
        self.client.post('/catalogos/bodegas/',
                         {'accion': 'toggle', 'bodega_id': bodega.pk})
        bodega.refresh_from_db()
        self.assertFalse(bodega.activa)

    def test_guard_no_desactiva_bodega_con_stock(self):
        bodega = Bodega.objects.create(nombre='Con stock')
        cat = Categoria.objects.create(nombre='Cat')
        item = Item.objects.create(codigo='A1', nombre='Cuaderno', categoria=cat)
        registrar_entrada(bodega=bodega, lineas=[(item, 5)], usuario=self.user)

        r = self.client.post('/catalogos/bodegas/',
                             {'accion': 'toggle', 'bodega_id': bodega.pk},
                             follow=True)
        bodega.refresh_from_db()
        self.assertTrue(bodega.activa)
        self.assertTrue(any('No se puede desactivar' in m for m in self._mensajes(r)))

    def test_bodega_con_stock_en_cero_si_se_desactiva_y_reactiva(self):
        """El guard mira la existencia ACTUAL: si el stock volvió a 0, la
        bodega sí se puede desactivar (y luego reactivar)."""
        bodega = Bodega.objects.create(nombre='Transitoria')
        cat = Categoria.objects.create(nombre='Cat')
        item = Item.objects.create(codigo='A1', nombre='Cuaderno', categoria=cat)
        registrar_entrada(bodega=bodega, lineas=[(item, 5)], usuario=self.user)
        registrar_salida(bodega=bodega, lineas=[(item, 5)], usuario=self.user)

        self.client.post('/catalogos/bodegas/',
                         {'accion': 'toggle', 'bodega_id': bodega.pk})
        bodega.refresh_from_db()
        self.assertFalse(bodega.activa)

        self.client.post('/catalogos/bodegas/',
                         {'accion': 'toggle', 'bodega_id': bodega.pk})
        bodega.refresh_from_db()
        self.assertTrue(bodega.activa)


class ItemsTest(_BaseCatalogosTest):

    def setUp(self):
        super().setUp()
        self.cat = Categoria.objects.create(nombre='Papelería')

    def _post_item(self, **extra):
        datos = {'codigo': 'LAP-01', 'nombre': 'Lápiz HB',
                 'categoria': self.cat.pk, 'unidad_medida': 'UNIDAD',
                 'descripcion': '', 'stock_minimo': 0, 'valor_unitario': '',
                 'activo': 'on'}
        datos.update(extra)
        return self.client.post('/articulos/guardar/', datos, follow=True)

    def test_crear_item(self):
        r = self._post_item()
        item = Item.objects.get(codigo='LAP-01')
        self.assertEqual(item.nombre, 'Lápiz HB')
        self.assertTrue(item.activo)
        self.assertTrue(any('creado' in m for m in self._mensajes(r)))

    def test_codigo_duplicado_no_crea(self):
        Item.objects.create(codigo='LAP-01', nombre='Otro', categoria=self.cat)
        r = self._post_item()
        self.assertEqual(Item.objects.count(), 1)
        self.assertTrue(self._mensajes(r))  # error legible vía messages

    def test_editar_item_y_desactivar(self):
        item = Item.objects.create(codigo='LAP-01', nombre='Lápiz',
                                   categoria=self.cat)
        # Sin 'activo' en el POST (checkbox desmarcado) el item queda inactivo.
        r = self._post_item(item_id=item.pk, nombre='Lápiz 2B',
                            stock_minimo=10, activo='')
        item.refresh_from_db()
        self.assertEqual(item.nombre, 'Lápiz 2B')
        self.assertEqual(item.stock_minimo, 10)
        self.assertFalse(item.activo)
        self.assertTrue(any('actualizado' in m for m in self._mensajes(r)))

    def test_lista_muestra_stock_total_y_bajo_minimo(self):
        item = Item.objects.create(codigo='LAP-01', nombre='Lápiz',
                                   categoria=self.cat, stock_minimo=10)
        b1 = Bodega.objects.create(nombre='B1')
        b2 = Bodega.objects.create(nombre='B2')
        registrar_entrada(bodega=b1, lineas=[(item, 3)], usuario=self.user)
        registrar_entrada(bodega=b2, lineas=[(item, 4)], usuario=self.user)

        r = self.client.get('/articulos/')
        self.assertContains(r, 'Lápiz')
        self.assertContains(r, 'Bajo mínimo')  # 7 <= 10, suma de bodegas


class TercerosTest(_BaseCatalogosTest):

    def test_crear_y_editar_tercero(self):
        self.client.post('/terceros/', {'nombre': 'Colegio San José',
                                        'documento': '900123', 'telefono': '',
                                        'notas': ''})
        tercero = Tercero.objects.get(documento='900123')
        self.client.post('/terceros/', {'tercero_id': tercero.pk,
                                        'nombre': 'Colegio San José',
                                        'documento': '900123',
                                        'telefono': '3001234567', 'notas': ''})
        tercero.refresh_from_db()
        self.assertEqual(tercero.telefono, '3001234567')

    def test_documento_duplicado_no_crea(self):
        Tercero.objects.create(nombre='Uno', documento='900123')
        r = self.client.post('/terceros/', {'nombre': 'Dos', 'documento': '900123',
                                            'telefono': '', 'notas': ''},
                             follow=True)
        self.assertEqual(Tercero.objects.count(), 1)
        self.assertTrue(any('documento' in m for m in self._mensajes(r)))

    def test_documento_vacio_se_repite_libre(self):
        Tercero.objects.create(nombre='Uno')
        self.client.post('/terceros/', {'nombre': 'Dos', 'documento': '',
                                        'telefono': '', 'notas': ''})
        self.assertEqual(Tercero.objects.count(), 2)

    def test_toggle_activo(self):
        tercero = Tercero.objects.create(nombre='Uno')
        self.client.post('/terceros/', {'accion': 'toggle',
                                        'tercero_id': tercero.pk})
        tercero.refresh_from_db()
        self.assertFalse(tercero.activo)


class TerceroAjaxCrearTest(_BaseCatalogosTest):
    """Contrato JSON que consumen los forms de salidas (F4) y préstamos (F5)."""

    def test_crear_ok(self):
        r = self.client.post('/terceros/ajax/crear/',
                             {'nombre': 'Asesor Pérez', 'documento': '123',
                              'telefono': '', 'notas': ''})
        self.assertEqual(r.status_code, 200)
        datos = r.json()
        self.assertTrue(datos['ok'])
        tercero = Tercero.objects.get(pk=datos['tercero']['id'])
        self.assertEqual(datos['tercero']['nombre'], tercero.nombre)
        self.assertEqual(datos['tercero']['documento'], '123')
        self.assertEqual(datos['tercero']['label'], str(tercero))

    def test_sin_nombre_devuelve_400(self):
        r = self.client.post('/terceros/ajax/crear/', {'nombre': ''})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()['ok'])
        self.assertTrue(r.json()['error'])

    def test_documento_duplicado_devuelve_400(self):
        Tercero.objects.create(nombre='Uno', documento='123')
        r = self.client.post('/terceros/ajax/crear/',
                             {'nombre': 'Dos', 'documento': '123'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('documento', r.json()['error'])

    def test_get_no_permitido(self):
        r = self.client.get('/terceros/ajax/crear/')
        self.assertEqual(r.status_code, 405)


class StockViewTest(_BaseCatalogosTest):

    def setUp(self):
        super().setUp()
        self.cat = Categoria.objects.create(nombre='Papelería')
        self.bodega = Bodega.objects.create(nombre='Principal')

    def test_existencias_sembradas_por_servicios(self):
        item = Item.objects.create(codigo='RES-01', nombre='Resma carta',
                                   categoria=self.cat)
        registrar_entrada(bodega=self.bodega, lineas=[(item, 25)],
                          usuario=self.user)
        r = self.client.get('/stock/')
        self.assertContains(r, 'Resma carta')
        self.assertContains(r, 'Principal')
        self.assertContains(r, '25')

    def test_resalta_bajo_minimo_y_respeta_minimo_cero(self):
        con_minimo = Item.objects.create(codigo='A1', nombre='Con mínimo',
                                         categoria=self.cat, stock_minimo=10)
        sin_minimo = Item.objects.create(codigo='A2', nombre='Sin mínimo',
                                         categoria=self.cat, stock_minimo=0)
        registrar_entrada(bodega=self.bodega,
                          lineas=[(con_minimo, 2), (sin_minimo, 1)],
                          usuario=self.user)
        r = self.client.get('/stock/')
        self.assertContains(r, 'Bajo mínimo')
        self.assertEqual(len(r.context['items_alerta']), 1)
        self.assertEqual(r.context['items_alerta'][0].pk, con_minimo.pk)

    def test_item_inactivo_no_aparece(self):
        item = Item.objects.create(codigo='A1', nombre='Viejo',
                                   categoria=self.cat)
        registrar_entrada(bodega=self.bodega, lineas=[(item, 5)],
                          usuario=self.user)
        item.activo = False
        item.save(update_fields=['activo'])
        r = self.client.get('/stock/')
        self.assertNotContains(r, 'Viejo')
        # La fila de Stock sigue existiendo (el kardex no se toca).
        self.assertTrue(Stock.objects.filter(item=item).exists())
