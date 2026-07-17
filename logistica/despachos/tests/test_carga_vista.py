"""Tests de la vista de carga (`/despachos/cargar/`): gates de área, enforcement
granular por módulo (LECTURA no puede cargar) y el POST feliz / inválido / viejo.

Arnés `Client(HTTP_HOST='logistica.testserver')`. No se toca storage: la carga
solo LEE el archivo subido (no lo guarda), así que no hace falta override de
MEDIA.
"""
import io

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

from core.areas import GRUPO_STAFF_FINANCIERA, GRUPO_STAFF_LOGISTICA

from logistica.despachos.models import CargaReporte, OrdenDespacho
from logistica.despachos.reporte import crear_reporte_bytes
from usuarios.models import ModuloUsuario

_URL = '/despachos/cargar/'


def _fila(**kw):
    base = {
        'sucursal': 'Principal', 'centro_costos': 'CC', 'bodega': 'BUCARAMANGA',
        'id_orden': 'PPAL-1', 'estado_orden_erp': 'Generada',
        'estado_facturacion': 'Pendiente', 'cliente': 'Colegio X',
        'id_cliente': 'CE 1', 'telefono': '3200000000', 'departamento': 'Santander',
        'ciudad': 'Bucaramanga', 'direccion': 'CALLE 1', 'categoria': 'EVALUACIÓN',
        'cod_articulo': '727', 'descripcion': 'SIM-1', 'cantidad': '17,00',
        'vendedor': 'V', 'observacion': 'o', 'vigencia': 'Orden vigente',
        'fecha_entrega': '2026-01-28', 'fecha_orden': '2026-01-28 11:22:29',
    }
    base.update(kw)
    return base


def _archivo(filas, nombre='reporte.xls', **kw):
    return SimpleUploadedFile(nombre, crear_reporte_bytes(filas, **kw),
                              content_type='application/vnd.ms-excel')


class GatesCargaTest(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST='logistica.testserver')
        self.user = User.objects.create_user(username='logis', password='pass')
        self.user.groups.add(Group.objects.get(name=GRUPO_STAFF_LOGISTICA))
        self.client.login(username='logis', password='pass')

    def test_anonimo_redirigido(self):
        c = Client(HTTP_HOST='logistica.testserver')
        self.assertEqual(c.get(_URL).status_code, 302)

    def test_usuario_otra_area_no_entra(self):
        u = User.objects.create_user(username='finan', password='pass')
        u.groups.add(Group.objects.get(name=GRUPO_STAFF_FINANCIERA))
        c = Client(HTTP_HOST='logistica.testserver')
        c.login(username='finan', password='pass')
        self.assertEqual(c.get(_URL).status_code, 302)

    def test_staff_logistica_ve_la_carga(self):
        self.assertEqual(self.client.get(_URL).status_code, 200)

    def test_lectura_no_puede_cargar(self):
        # Override a LECTURA: puede ver la página (GET) pero el POST (escritura) lo
        # bloquea el middleware granular por módulo.
        ModuloUsuario.objects.create(user=self.user, area='logistica',
                                     modulo='despachos',
                                     nivel=ModuloUsuario.Nivel.LECTURA)
        self.assertEqual(self.client.get(_URL).status_code, 200)
        resp = self.client.post(_URL, {'archivo': _archivo([_fila()])})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(CargaReporte.objects.exists())


class PostCargaTest(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST='logistica.testserver')
        self.user = User.objects.create_user(username='logis', password='pass')
        self.user.groups.add(Group.objects.get(name=GRUPO_STAFF_LOGISTICA))
        self.client.login(username='logis', password='pass')

    def _mensajes(self, response):
        return [str(m) for m in response.context['messages']]

    def test_post_feliz_importa(self):
        resp = self.client.post(_URL, {
            'archivo': _archivo([_fila(id_orden='PPAL-1'), _fila(id_orden='PPAL-2')]),
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(OrdenDespacho.objects.count(), 2)
        self.assertEqual(CargaReporte.objects.count(), 1)
        self.assertTrue(any('importado' in m.lower() for m in self._mensajes(resp)))

    def test_extension_invalida_rechazada(self):
        resp = self.client.post(_URL, {
            'archivo': _archivo([_fila()], nombre='reporte.txt'),
        }, follow=True)
        self.assertFalse(CargaReporte.objects.exists())
        self.assertTrue(self._mensajes(resp))

    def test_reporte_sin_columnas_obligatorias(self):
        # Quita 'id_orden' de las columnas emitidas → ReporteInvalido.
        from logistica.despachos.reporte import _ORDEN_CAMPOS
        cols = [c for c in _ORDEN_CAMPOS if c != 'id_orden']
        resp = self.client.post(_URL, {
            'archivo': _archivo([_fila()], columnas=cols),
        }, follow=True)
        self.assertFalse(CargaReporte.objects.exists())
        self.assertTrue(any('columnas' in m.lower() for m in self._mensajes(resp)))

    def test_archivo_viejo_rechazado(self):
        self.client.post(_URL, {
            'archivo': _archivo([_fila(fecha_orden='2026-02-10 10:00:00')]),
        })
        resp = self.client.post(_URL, {
            'archivo': _archivo([_fila(id_orden='PPAL-9',
                                       fecha_orden='2026-01-01 08:00:00')]),
        }, follow=True)
        self.assertEqual(CargaReporte.objects.count(), 1)  # el viejo no creó carga
        self.assertTrue(any('antiguo' in m.lower() for m in self._mensajes(resp)))
