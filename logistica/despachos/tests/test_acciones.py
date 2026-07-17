"""Tests de las acciones de F4: estado de trabajo (alistar/despachar/revertir) y
cambio de material por línea (registrar/revertir/toggle ERP).

Dos frentes:
- **Servicios** (`marcar_estado`, `registrar_cambio_material`, …): transiciones
  válidas/inválidas, campos usuario+timestamp, eventos append-only, guardas de
  estado terminal. ORM directo, sin HTTP.
- **Vistas** (`/despachos/orden|linea/…`): gates de área + enforcement granular
  (LECTURA bloquea las escrituras), POST feliz y traducción de errores a toasts.

Cierra con la **integración con el import** (F2): una orden despachada aquí que
llega anulada+remitida en el reporte → REMITIDA sin `cerrada_sin_marcar`.

Arnés `Client(HTTP_HOST='logistica.testserver')`; imports absolutos.
"""
import io
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import Client, TestCase
from django.utils import timezone

from core.areas import GRUPO_STAFF_LOGISTICA

from logistica.despachos.models import (ArticuloERP, EventoOrden, LineaOrden,
                                        OrdenDespacho)
from logistica.despachos.reporte import crear_reporte_bytes
from logistica.despachos.services import (TransicionInvalida, importar_reporte,
                                          marcar_erp_actualizado, marcar_estado,
                                          registrar_cambio_material,
                                          revertir_cambio_material)
from usuarios.models import ModuloUsuario

Estado = OrdenDespacho.Estado
Tipo = EventoOrden.Tipo


def _orden(id_orden='PPAL-1', *, estado=Estado.PENDIENTE, **kw):
    return OrdenDespacho.objects.create(id_orden=id_orden, estado=estado, **kw)


# ===========================================================================
# Servicios de estado
# ===========================================================================

class MarcarEstadoTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u', password='x')

    def test_alistar_desde_pendiente(self):
        o = _orden(estado=Estado.PENDIENTE)
        marcar_estado(orden=o, accion='alistar', usuario=self.user)
        o.refresh_from_db()
        self.assertEqual(o.estado, Estado.ALISTADA)
        self.assertEqual(o.alistada_por, self.user)
        self.assertIsNotNone(o.alistada_en)
        self.assertTrue(o.eventos.filter(tipo=Tipo.ALISTADA, usuario=self.user).exists())

    def test_despachar_desde_alistada(self):
        o = _orden(estado=Estado.ALISTADA)
        marcar_estado(orden=o, accion='despachar', usuario=self.user)
        o.refresh_from_db()
        self.assertEqual(o.estado, Estado.DESPACHADA)
        self.assertEqual(o.despachada_por, self.user)
        self.assertIsNotNone(o.despachada_en)
        self.assertTrue(o.eventos.filter(tipo=Tipo.DESPACHADA).exists())

    def test_revertir_despacho_vuelve_a_alistada_y_limpia_alerta(self):
        o = _orden(estado=Estado.DESPACHADA, despachada_por=self.user,
                   despachada_en=timezone.now(), alerta_remision=True)
        marcar_estado(orden=o, accion='revertir', usuario=self.user)
        o.refresh_from_db()
        self.assertEqual(o.estado, Estado.ALISTADA)
        self.assertIsNone(o.despachada_por)
        self.assertIsNone(o.despachada_en)
        self.assertFalse(o.alerta_remision)
        self.assertTrue(o.eventos.filter(tipo=Tipo.REVERTIDA).exists())

    def test_revertir_alistamiento_vuelve_a_pendiente(self):
        o = _orden(estado=Estado.ALISTADA, alistada_por=self.user,
                   alistada_en=timezone.now())
        marcar_estado(orden=o, accion='revertir', usuario=self.user)
        o.refresh_from_db()
        self.assertEqual(o.estado, Estado.PENDIENTE)
        self.assertIsNone(o.alistada_por)
        self.assertIsNone(o.alistada_en)

    def test_no_se_puede_saltar_despachar_desde_pendiente(self):
        o = _orden(estado=Estado.PENDIENTE)
        with self.assertRaises(TransicionInvalida):
            marcar_estado(orden=o, accion='despachar', usuario=self.user)

    def test_no_se_puede_alistar_una_alistada(self):
        o = _orden(estado=Estado.ALISTADA)
        with self.assertRaises(TransicionInvalida):
            marcar_estado(orden=o, accion='alistar', usuario=self.user)

    def test_revertir_pendiente_es_invalido(self):
        o = _orden(estado=Estado.PENDIENTE)
        with self.assertRaises(TransicionInvalida):
            marcar_estado(orden=o, accion='revertir', usuario=self.user)

    def test_terminal_rechaza_todo(self):
        for term in (Estado.REMITIDA, Estado.ANULADA):
            o = _orden(id_orden=f'PPAL-{term}', estado=term)
            for accion in ('alistar', 'despachar', 'revertir'):
                with self.assertRaises(TransicionInvalida):
                    marcar_estado(orden=o, accion=accion, usuario=self.user)

    def test_accion_desconocida_es_invalida(self):
        o = _orden(estado=Estado.PENDIENTE)
        with self.assertRaises(TransicionInvalida):
            marcar_estado(orden=o, accion='inventada', usuario=self.user)

    def test_no_deja_evento_si_la_transicion_falla(self):
        o = _orden(estado=Estado.PENDIENTE)
        with self.assertRaises(TransicionInvalida):
            marcar_estado(orden=o, accion='despachar', usuario=self.user)
        self.assertEqual(o.eventos.count(), 0)


# ===========================================================================
# Servicios de cambio de material
# ===========================================================================

class CambioMaterialTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u', password='x')
        self.orden = _orden(estado=Estado.PENDIENTE)
        self.art = ArticuloERP.objects.create(codigo='727', descripcion='SIM-1')
        self.art_nuevo = ArticuloERP.objects.create(codigo='728', descripcion='SIM-2')
        self.linea = LineaOrden.objects.create(
            orden=self.orden, articulo=self.art, cod_articulo='727',
            descripcion='SIM-1', categoria='EVALUACIÓN', cantidad=Decimal('5'),
            es_material=True, orden_archivo=0)

    def test_registrar_cambio(self):
        registrar_cambio_material(linea=self.linea, articulo_destino=self.art_nuevo,
                                  cantidad='3', usuario=self.user)
        self.linea.refresh_from_db()
        self.assertEqual(self.linea.articulo_cambio, self.art_nuevo)
        self.assertEqual(self.linea.cantidad_cambio, Decimal('3'))
        self.assertEqual(self.linea.cambiado_por, self.user)
        self.assertIsNotNone(self.linea.cambiado_en)
        self.assertTrue(self.linea.pendiente_erp)
        self.assertTrue(self.orden.eventos.filter(tipo=Tipo.CAMBIO_MATERIAL).exists())

    def test_registrar_cambio_cantidad_no_positiva(self):
        with self.assertRaises(ValueError):
            registrar_cambio_material(linea=self.linea, articulo_destino=self.art_nuevo,
                                      cantidad='0', usuario=self.user)

    def test_registrar_cambio_en_orden_terminal_falla(self):
        self.orden.estado = Estado.REMITIDA
        self.orden.save(update_fields=['estado'])
        self.linea.refresh_from_db()  # recarga la FK orden con el nuevo estado
        with self.assertRaises(TransicionInvalida):
            registrar_cambio_material(linea=self.linea, articulo_destino=self.art_nuevo,
                                      cantidad='3', usuario=self.user)

    def test_revertir_cambio(self):
        registrar_cambio_material(linea=self.linea, articulo_destino=self.art_nuevo,
                                  cantidad='3', usuario=self.user)
        revertir_cambio_material(linea=self.linea, usuario=self.user)
        self.linea.refresh_from_db()
        self.assertIsNone(self.linea.articulo_cambio)
        self.assertIsNone(self.linea.cantidad_cambio)
        self.assertFalse(self.linea.pendiente_erp)
        self.assertTrue(self.orden.eventos.filter(tipo=Tipo.CAMBIO_REVERTIDO).exists())

    def test_revertir_sin_cambio_falla(self):
        with self.assertRaises(TransicionInvalida):
            revertir_cambio_material(linea=self.linea, usuario=self.user)

    def test_toggle_erp_marca_hecho(self):
        registrar_cambio_material(linea=self.linea, articulo_destino=self.art_nuevo,
                                  cantidad='3', usuario=self.user)
        marcar_erp_actualizado(linea=self.linea, usuario=self.user, hecho=True)
        self.linea.refresh_from_db()
        self.assertFalse(self.linea.pendiente_erp)
        self.assertTrue(self.orden.eventos.filter(tipo=Tipo.ERP_ACTUALIZADO).exists())

    def test_toggle_erp_reabre_pendiente(self):
        registrar_cambio_material(linea=self.linea, articulo_destino=self.art_nuevo,
                                  cantidad='3', usuario=self.user)
        marcar_erp_actualizado(linea=self.linea, usuario=self.user, hecho=True)
        marcar_erp_actualizado(linea=self.linea, usuario=self.user, hecho=False)
        self.linea.refresh_from_db()
        self.assertTrue(self.linea.pendiente_erp)

    def test_toggle_erp_sin_cambio_falla(self):
        with self.assertRaises(TransicionInvalida):
            marcar_erp_actualizado(linea=self.linea, usuario=self.user, hecho=True)


# ===========================================================================
# Vistas (HTTP)
# ===========================================================================

class _BaseVista(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST='logistica.testserver')
        self.user = User.objects.create_user(username='logis', password='pass')
        self.user.groups.add(Group.objects.get(name=GRUPO_STAFF_LOGISTICA))
        self.client.login(username='logis', password='pass')
        self.orden = _orden(estado=Estado.PENDIENTE)


class VistaEstadoTest(_BaseVista):
    def test_alistar_por_post(self):
        resp = self.client.post(f'/despachos/orden/{self.orden.pk}/estado/',
                                {'accion': 'alistar'})
        self.assertEqual(resp.status_code, 302)
        self.orden.refresh_from_db()
        self.assertEqual(self.orden.estado, Estado.ALISTADA)

    def test_next_seguro_redirige_al_tablero(self):
        resp = self.client.post(f'/despachos/orden/{self.orden.pk}/estado/',
                                {'accion': 'alistar', 'next': '/despachos/?tab=abiertas'})
        self.assertRedirects(resp, '/despachos/?tab=abiertas',
                             fetch_redirect_response=False)

    def test_next_externo_se_ignora(self):
        resp = self.client.post(f'/despachos/orden/{self.orden.pk}/estado/',
                                {'accion': 'alistar', 'next': 'http://evil.com/'})
        self.assertRedirects(resp, f'/despachos/orden/{self.orden.pk}/',
                             fetch_redirect_response=False)

    def test_transicion_invalida_no_revienta(self):
        resp = self.client.post(f'/despachos/orden/{self.orden.pk}/estado/',
                                {'accion': 'despachar'})
        self.assertEqual(resp.status_code, 302)
        self.orden.refresh_from_db()
        self.assertEqual(self.orden.estado, Estado.PENDIENTE)  # sin cambios

    def test_get_no_permitido(self):
        # @require_POST → 405 al GET.
        self.assertEqual(
            self.client.get(f'/despachos/orden/{self.orden.pk}/estado/').status_code, 405)

    def test_lectura_no_puede_escribir(self):
        ModuloUsuario.objects.create(user=self.user, area='logistica',
                                     modulo='despachos',
                                     nivel=ModuloUsuario.Nivel.LECTURA)
        resp = self.client.post(f'/despachos/orden/{self.orden.pk}/estado/',
                                {'accion': 'alistar'})
        self.assertEqual(resp.status_code, 403)
        self.orden.refresh_from_db()
        self.assertEqual(self.orden.estado, Estado.PENDIENTE)


class VistaCambioMaterialTest(_BaseVista):
    def setUp(self):
        super().setUp()
        self.art_nuevo = ArticuloERP.objects.create(codigo='728', descripcion='SIM-2')
        self.linea = LineaOrden.objects.create(
            orden=self.orden, cod_articulo='727', descripcion='SIM-1',
            categoria='EVALUACIÓN', cantidad=Decimal('5'), es_material=True)

    def test_cambio_por_post(self):
        resp = self.client.post(f'/despachos/linea/{self.linea.pk}/cambio/',
                                {'articulo_id': self.art_nuevo.pk, 'cantidad': '3'})
        self.assertRedirects(resp, f'/despachos/orden/{self.orden.pk}/',
                             fetch_redirect_response=False)
        self.linea.refresh_from_db()
        self.assertEqual(self.linea.articulo_cambio, self.art_nuevo)
        self.assertTrue(self.linea.pendiente_erp)

    def test_cambio_sin_articulo_avisa(self):
        resp = self.client.post(f'/despachos/linea/{self.linea.pk}/cambio/',
                                {'articulo_id': '', 'cantidad': '3'})
        self.assertEqual(resp.status_code, 302)
        self.linea.refresh_from_db()
        self.assertFalse(self.linea.tiene_cambio)

    def test_cambio_cantidad_con_coma(self):
        resp = self.client.post(f'/despachos/linea/{self.linea.pk}/cambio/',
                                {'articulo_id': self.art_nuevo.pk, 'cantidad': '2,50'})
        self.assertEqual(resp.status_code, 302)
        self.linea.refresh_from_db()
        self.assertEqual(self.linea.cantidad_cambio, Decimal('2.50'))

    def test_quitar_cambio(self):
        registrar_cambio_material(linea=self.linea, articulo_destino=self.art_nuevo,
                                  cantidad='3', usuario=self.user)
        resp = self.client.post(f'/despachos/linea/{self.linea.pk}/cambio/quitar/')
        self.assertEqual(resp.status_code, 302)
        self.linea.refresh_from_db()
        self.assertFalse(self.linea.tiene_cambio)

    def test_toggle_erp(self):
        registrar_cambio_material(linea=self.linea, articulo_destino=self.art_nuevo,
                                  cantidad='3', usuario=self.user)
        resp = self.client.post(f'/despachos/linea/{self.linea.pk}/erp/', {'hecho': '1'})
        self.assertEqual(resp.status_code, 302)
        self.linea.refresh_from_db()
        self.assertFalse(self.linea.pendiente_erp)

    def test_lectura_no_puede_cambiar(self):
        ModuloUsuario.objects.create(user=self.user, area='logistica',
                                     modulo='despachos',
                                     nivel=ModuloUsuario.Nivel.LECTURA)
        resp = self.client.post(f'/despachos/linea/{self.linea.pk}/cambio/',
                                {'articulo_id': self.art_nuevo.pk, 'cantidad': '3'})
        self.assertEqual(resp.status_code, 403)


# ===========================================================================
# Integración con el import (F2)
# ===========================================================================

class IntegracionImportTest(TestCase):
    """Despachar una orden aquí y luego importar el reporte con esa orden ya
    anulada+remitida en el ERP → cierre automático a REMITIDA SIN
    `cerrada_sin_marcar` (se marcó el despacho antes) y evento CIERRE_AUTO."""

    def setUp(self):
        self.user = User.objects.create_user(username='u', password='x')

    def _fila(self, **kw):
        base = {
            'sucursal': 'Principal', 'centro_costos': 'CC', 'bodega': 'BUCARAMANGA',
            'id_orden': 'PPAL-1', 'estado_orden_erp': 'Generada',
            'estado_facturacion': 'Pendiente', 'cliente': 'Colegio X',
            'id_cliente': 'CE 1', 'telefono': '3200000000', 'departamento': 'Santander',
            'ciudad': 'Bucaramanga', 'direccion': 'CALLE 1', 'categoria': 'EVALUACIÓN',
            'cod_articulo': '727', 'descripcion': 'SIM-1', 'cantidad': '17,00',
            'vendedor': 'V', 'observacion': 'obs', 'vigencia': 'Orden vigente',
            'fecha_entrega': '2026-01-28', 'fecha_orden': '2026-01-28 11:22:29',
        }
        base.update(kw)
        return base

    def _importar(self, filas):
        datos = crear_reporte_bytes(filas)
        return importar_reporte(archivo=io.BytesIO(datos),
                                nombre_archivo='r.xls', usuario=self.user)

    def test_despachada_luego_remitida_no_cerrada_sin_marcar(self):
        # 1) Primer import: orden vigente + pendiente.
        self._importar([self._fila()])
        o = OrdenDespacho.objects.get(id_orden='PPAL-1')
        # 2) Se alista y despacha aquí.
        marcar_estado(orden=o, accion='alistar', usuario=self.user)
        marcar_estado(orden=o, accion='despachar', usuario=self.user)
        # 3) Segundo import: el ERP la cerró (anulada + remisión).
        self._importar([self._fila(vigencia='Orden anulada',
                                   estado_facturacion='Remisión de venta PPAL-1')])
        o.refresh_from_db()
        self.assertEqual(o.estado, Estado.REMITIDA)
        self.assertFalse(o.cerrada_sin_marcar)
        self.assertTrue(o.eventos.filter(tipo=Tipo.CIERRE_AUTO).exists())
        self.assertFalse(o.eventos.filter(tipo=Tipo.CIERRE_SIN_MARCAR).exists())
