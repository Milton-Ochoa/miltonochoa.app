"""Tests de la Fase 4 (movimientos UI): gates, POST de entradas/salidas/
traslados (con re-render en error y nada escrito), modal de ajuste, kardex,
ledger global y adjuntos de entrada (subir/descargar proxiado/eliminar).

Mismo arnés que tests_catalogos.py: `Client(HTTP_HOST='logistica.testserver')`.
Los archivos usan storage LOCAL en tmp (override de MEDIA_ROOT/STORAGES):
NUNCA tocan Supabase.
"""
import shutil
import tempfile

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from core.areas import GRUPO_STAFF_FINANCIERA, GRUPO_STAFF_LOGISTICA

from .models import (AdjuntoEntrada, Bodega, Categoria, Entrada, Item,
                     Movimiento, Salida, Stock, Tercero, Traslado)
from .services import registrar_entrada

_STORAGE_LOCAL = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
_MEDIA_TMP = tempfile.mkdtemp()


class _BaseMovimientosTest(TestCase):
    """Cliente del subdominio + staff logueado + catálogo mínimo sembrado."""

    def setUp(self):
        self.client = Client(HTTP_HOST='logistica.testserver')
        self.user = User.objects.create_user(username='logis', password='pass')
        self.user.groups.add(Group.objects.get(name=GRUPO_STAFF_LOGISTICA))
        self.client.login(username='logis', password='pass')

        self.categoria = Categoria.objects.create(nombre='Papelería')
        self.bodega = Bodega.objects.create(nombre='Principal')
        self.bodega2 = Bodega.objects.create(nombre='Sucursal')
        self.item = Item.objects.create(codigo='RES-01', nombre='Resma carta',
                                        categoria=self.categoria)
        self.item2 = Item.objects.create(codigo='MAR-01', nombre='Marcadores',
                                         categoria=self.categoria)

    def _mensajes(self, response):
        return [str(m) for m in response.context['messages']]

    def _stock(self, item, bodega):
        fila = Stock.objects.filter(item=item, bodega=bodega).first()
        return fila.cantidad if fila else 0

    def _sembrar(self, item, bodega, cantidad):
        registrar_entrada(bodega=bodega, lineas=[(item, cantidad)],
                          usuario=self.user)


class GatesMovimientosTest(_BaseMovimientosTest):

    def _urls(self):
        return ['/entradas/', '/entradas/nueva/', '/salidas/', '/salidas/nueva/',
                '/traslados/', '/traslados/nuevo/', '/movimientos/',
                f'/articulos/{self.item.pk}/kardex/']

    def test_anonimo_redirigido(self):
        c = Client(HTTP_HOST='logistica.testserver')
        for url in self._urls():
            self.assertEqual(c.get(url).status_code, 302, url)

    def test_usuario_de_otra_area_no_entra(self):
        u = User.objects.create_user(username='finan', password='pass')
        u.groups.add(Group.objects.get(name=GRUPO_STAFF_FINANCIERA))
        c = Client(HTTP_HOST='logistica.testserver')
        c.login(username='finan', password='pass')
        for url in self._urls():
            self.assertEqual(c.get(url).status_code, 302, url)

    def test_staff_logistica_ve_todas_las_vistas(self):
        for url in self._urls():
            self.assertEqual(self.client.get(url).status_code, 200, url)


class EntradaUITest(_BaseMovimientosTest):

    def test_post_entrada_crea_doc_stock_y_kardex(self):
        r = self.client.post('/entradas/nueva/', {
            'bodega': self.bodega.pk, 'proveedor': 'ACME', 'observaciones': '',
            'linea_item': [self.item.pk, self.item2.pk],
            'linea_cantidad': ['10', '5'],
        }, follow=True)
        entrada = Entrada.objects.get()
        self.assertEqual(entrada.proveedor, 'ACME')
        self.assertEqual(entrada.lineas.count(), 2)
        self.assertEqual(self._stock(self.item, self.bodega), 10)
        self.assertEqual(self._stock(self.item2, self.bodega), 5)
        movs = Movimiento.objects.filter(entrada=entrada)
        self.assertEqual(movs.count(), 2)
        self.assertTrue(all(m.tipo == Movimiento.Tipo.ENTRADA for m in movs))
        # POST-redirect al detalle + toast
        self.assertEqual(r.request['PATH_INFO'], f'/entradas/{entrada.pk}/')
        self.assertTrue(any('registrada' in m for m in self._mensajes(r)))

    def test_post_sin_lineas_no_crea_nada(self):
        r = self.client.post('/entradas/nueva/', {
            'bodega': self.bodega.pk, 'proveedor': '',
            'linea_item': [''], 'linea_cantidad': [''],
        })
        self.assertEqual(r.status_code, 200)  # re-render, no redirect
        self.assertFalse(Entrada.objects.exists())
        self.assertTrue(any('al menos una línea' in m for m in self._mensajes(r)))

    def test_post_cantidad_invalida_no_crea_nada(self):
        r = self.client.post('/entradas/nueva/', {
            'bodega': self.bodega.pk,
            'linea_item': [self.item.pk], 'linea_cantidad': ['abc'],
        })
        self.assertFalse(Entrada.objects.exists())
        self.assertTrue(any('cantidad inválida' in m for m in self._mensajes(r)))

    def test_bodega_inactiva_rechazada(self):
        self.bodega.activa = False
        self.bodega.save(update_fields=['activa'])
        r = self.client.post('/entradas/nueva/', {
            'bodega': self.bodega.pk,
            'linea_item': [self.item.pk], 'linea_cantidad': ['3'],
        })
        self.assertFalse(Entrada.objects.exists())
        self.assertTrue(self._mensajes(r))  # error legible del form

    def test_item_inactivo_rechazado(self):
        self.item.activo = False
        self.item.save(update_fields=['activo'])
        r = self.client.post('/entradas/nueva/', {
            'bodega': self.bodega.pk,
            'linea_item': [self.item.pk], 'linea_cantidad': ['3'],
        })
        self.assertFalse(Entrada.objects.exists())
        self.assertTrue(any('inválido o inactivo' in m for m in self._mensajes(r)))

    def test_detalle_muestra_lineas(self):
        self._sembrar(self.item, self.bodega, 7)
        entrada = Entrada.objects.get()
        r = self.client.get(f'/entradas/{entrada.pk}/')
        self.assertContains(r, 'Resma carta')
        self.assertContains(r, 'Principal')


class SalidaUITest(_BaseMovimientosTest):

    def test_post_salida_con_tercero_snapshotea(self):
        self._sembrar(self.item, self.bodega, 10)
        tercero = Tercero.objects.create(nombre='Colegio Norte')
        r = self.client.post('/salidas/nueva/', {
            'bodega': self.bodega.pk, 'tercero': tercero.pk,
            'motivo': 'Entrega de material', 'observaciones': '',
            'linea_item': [self.item.pk], 'linea_cantidad': ['4'],
        }, follow=True)
        salida = Salida.objects.get()
        self.assertEqual(salida.tercero_nombre, 'Colegio Norte')
        self.assertEqual(self._stock(self.item, self.bodega), 6)
        self.assertTrue(any('registrada' in m for m in self._mensajes(r)))

    def test_stock_insuficiente_no_escribe_nada(self):
        self._sembrar(self.item, self.bodega, 3)
        r = self.client.post('/salidas/nueva/', {
            'bodega': self.bodega.pk, 'tercero': '', 'motivo': '',
            'linea_item': [self.item.pk], 'linea_cantidad': ['10'],
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Salida.objects.exists())
        self.assertEqual(self._stock(self.item, self.bodega), 3)
        self.assertTrue(any('Stock insuficiente' in m for m in self._mensajes(r)))

    def test_multilinea_insuficiente_revierte_todo(self):
        # La línea 1 alcanza y la 2 no: el atomic del servicio revierte TODO.
        self._sembrar(self.item, self.bodega, 10)
        self.client.post('/salidas/nueva/', {
            'bodega': self.bodega.pk, 'tercero': '', 'motivo': '',
            'linea_item': [self.item.pk, self.item2.pk],
            'linea_cantidad': ['2', '1'],
        })
        self.assertFalse(Salida.objects.exists())
        self.assertEqual(self._stock(self.item, self.bodega), 10)
        self.assertFalse(Movimiento.objects.filter(
            tipo=Movimiento.Tipo.SALIDA).exists())


class TrasladoUITest(_BaseMovimientosTest):

    def test_post_traslado_mueve_stock(self):
        self._sembrar(self.item, self.bodega, 8)
        r = self.client.post('/traslados/nuevo/', {
            'bodega_origen': self.bodega.pk, 'bodega_destino': self.bodega2.pk,
            'linea_item': [self.item.pk], 'linea_cantidad': ['5'],
        }, follow=True)
        traslado = Traslado.objects.get()
        self.assertEqual(self._stock(self.item, self.bodega), 3)
        self.assertEqual(self._stock(self.item, self.bodega2), 5)
        self.assertEqual(traslado.movimientos.count(), 2)  # SAL + ENT
        self.assertTrue(any('registrado' in m for m in self._mensajes(r)))

    def test_misma_bodega_rechazada(self):
        self._sembrar(self.item, self.bodega, 8)
        r = self.client.post('/traslados/nuevo/', {
            'bodega_origen': self.bodega.pk, 'bodega_destino': self.bodega.pk,
            'linea_item': [self.item.pk], 'linea_cantidad': ['2'],
        })
        self.assertFalse(Traslado.objects.exists())
        self.assertTrue(any('distintas' in m for m in self._mensajes(r)))

    def test_traslado_insuficiente_no_escribe(self):
        self._sembrar(self.item, self.bodega, 2)
        self.client.post('/traslados/nuevo/', {
            'bodega_origen': self.bodega.pk, 'bodega_destino': self.bodega2.pk,
            'linea_item': [self.item.pk], 'linea_cantidad': ['5'],
        })
        self.assertFalse(Traslado.objects.exists())
        self.assertEqual(self._stock(self.item, self.bodega), 2)
        self.assertEqual(self._stock(self.item, self.bodega2), 0)


class AjusteUITest(_BaseMovimientosTest):

    def test_ajuste_valido_cambia_stock_y_asienta(self):
        self._sembrar(self.item, self.bodega, 10)
        r = self.client.post('/ajustes/nuevo/', {
            'item_id': self.item.pk, 'bodega_id': self.bodega.pk,
            'nueva_cantidad': '7', 'motivo': 'Conteo físico',
        }, follow=True)
        self.assertEqual(self._stock(self.item, self.bodega), 7)
        mov = Movimiento.objects.filter(tipo=Movimiento.Tipo.AJUSTE_NEG).get()
        self.assertEqual(mov.cantidad, 3)
        self.assertIn('Conteo físico', mov.detalle)
        self.assertTrue(any('ajustado a 7' in m for m in self._mensajes(r)))

    def test_ajuste_sin_motivo_rechazado(self):
        self._sembrar(self.item, self.bodega, 10)
        r = self.client.post('/ajustes/nuevo/', {
            'item_id': self.item.pk, 'bodega_id': self.bodega.pk,
            'nueva_cantidad': '7', 'motivo': '   ',
        }, follow=True)
        self.assertEqual(self._stock(self.item, self.bodega), 10)
        self.assertTrue(any('motivo' in m for m in self._mensajes(r)))

    def test_ajuste_cantidad_no_numerica_rechazada(self):
        self._sembrar(self.item, self.bodega, 10)
        r = self.client.post('/ajustes/nuevo/', {
            'item_id': self.item.pk, 'bodega_id': self.bodega.pk,
            'nueva_cantidad': 'xx', 'motivo': 'Conteo',
        }, follow=True)
        self.assertEqual(self._stock(self.item, self.bodega), 10)
        self.assertTrue(any('número entero' in m for m in self._mensajes(r)))

    def test_ajuste_sin_cambio_rechazado(self):
        self._sembrar(self.item, self.bodega, 10)
        r = self.client.post('/ajustes/nuevo/', {
            'item_id': self.item.pk, 'bodega_id': self.bodega.pk,
            'nueva_cantidad': '10', 'motivo': 'Conteo',
        }, follow=True)
        self.assertTrue(any('no cambia' in m for m in self._mensajes(r)))
        self.assertFalse(Movimiento.objects.filter(
            tipo__in=[Movimiento.Tipo.AJUSTE_POS,
                      Movimiento.Tipo.AJUSTE_NEG]).exists())


class KardexYLedgerTest(_BaseMovimientosTest):

    def test_kardex_muestra_movimientos_con_saldo(self):
        self._sembrar(self.item, self.bodega, 10)
        self._sembrar(self.item, self.bodega2, 4)
        r = self.client.get(f'/articulos/{self.item.pk}/kardex/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['movimientos']), 2)

    def test_kardex_filtra_por_bodega(self):
        self._sembrar(self.item, self.bodega, 10)
        self._sembrar(self.item, self.bodega2, 4)
        r = self.client.get(f'/articulos/{self.item.pk}/kardex/?bodega={self.bodega2.pk}')
        movs = list(r.context['movimientos'])
        self.assertEqual(len(movs), 1)
        self.assertEqual(movs[0].bodega, self.bodega2)
        self.assertEqual(movs[0].saldo_resultante, 4)

    def test_kardex_fechas_invalidas_se_ignoran(self):
        self._sembrar(self.item, self.bodega, 10)
        r = self.client.get(f'/articulos/{self.item.pk}/kardex/?desde=no-fecha&hasta=')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['movimientos']), 1)

    def test_ledger_global_lista_movimientos(self):
        self._sembrar(self.item, self.bodega, 10)
        r = self.client.get('/movimientos/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['movimientos']), 1)
        self.assertContains(r, 'Resma carta')


@override_settings(MEDIA_ROOT=_MEDIA_TMP, STORAGES=_STORAGE_LOCAL)
class AdjuntosEntradaTest(_BaseMovimientosTest):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_MEDIA_TMP, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self._sembrar(self.item, self.bodega, 5)
        self.entrada = Entrada.objects.get()

    def _subir(self, nombre='factura.pdf', contenido=b'%PDF-1.4 datos'):
        return self.client.post(
            f'/entradas/{self.entrada.pk}/adjuntos/subir/',
            {'archivo': SimpleUploadedFile(nombre, contenido)}, follow=True)

    def test_subir_y_listar_adjunto(self):
        r = self._subir()
        adjunto = AdjuntoEntrada.objects.get()
        self.assertEqual(adjunto.entrada, self.entrada)
        self.assertTrue(adjunto.archivo.storage.exists(adjunto.archivo.name))
        # El upload_to renombra: entrada-<id>-<slug>.pdf
        self.assertIn(f'entrada-{self.entrada.pk}-factura', adjunto.archivo.name)
        self.assertContains(r, adjunto.nombre_mostrar)

    def test_extension_invalida_rechazada(self):
        r = self._subir(nombre='virus.exe', contenido=b'MZ')
        self.assertFalse(AdjuntoEntrada.objects.exists())
        self.assertTrue(any('no permitido' in m for m in self._mensajes(r)))

    def test_tamano_excesivo_rechazado(self):
        r = self._subir(contenido=b'x' * (10 * 1024 * 1024 + 1))
        self.assertFalse(AdjuntoEntrada.objects.exists())
        self.assertTrue(any('10 MB' in m for m in self._mensajes(r)))

    def test_descarga_proxiada_attachment_e_inline(self):
        self._subir()
        adjunto = AdjuntoEntrada.objects.get()
        r = self.client.get(f'/entradas/adjuntos/{adjunto.pk}/descargar/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('attachment', r['Content-Disposition'])
        r = self.client.get(f'/entradas/adjuntos/{adjunto.pk}/descargar/?inline=1')
        self.assertIn('inline', r['Content-Disposition'])

    def test_descarga_gated_a_otra_area(self):
        self._subir()
        adjunto = AdjuntoEntrada.objects.get()
        u = User.objects.create_user(username='finan', password='pass')
        u.groups.add(Group.objects.get(name=GRUPO_STAFF_FINANCIERA))
        c = Client(HTTP_HOST='logistica.testserver')
        c.login(username='finan', password='pass')
        r = c.get(f'/entradas/adjuntos/{adjunto.pk}/descargar/')
        self.assertEqual(r.status_code, 302)

    def test_eliminar_borra_fila_y_archivo(self):
        self._subir()
        adjunto = AdjuntoEntrada.objects.get()
        storage, nombre = adjunto.archivo.storage, adjunto.archivo.name
        r = self.client.post(f'/entradas/adjuntos/{adjunto.pk}/eliminar/',
                             follow=True)
        self.assertFalse(AdjuntoEntrada.objects.exists())
        self.assertFalse(storage.exists(nombre))
        self.assertTrue(any('eliminado' in m for m in self._mensajes(r)))
