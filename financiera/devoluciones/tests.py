"""Tests de las devoluciones de colegios en financiera (F6): gate por área,
solo lectura (no existe ruta de escritura), export con el MISMO layout que
logística y respeto del contrato "financiera no muestra toasts".

Arnés del área: `Client(HTTP_HOST='financiera.testserver')`; los datos se siembran
con el servicio de inventario (única puerta de escritura al stock).
"""
import io
from datetime import date

from django.contrib.auth.models import Group, User
from django.test import Client, TestCase
from openpyxl import load_workbook

from core.areas import GRUPO_STAFF_FINANCIERA, GRUPO_STAFF_LOGISTICA
from logistica.inventario.models import Bodega, Categoria
from logistica.inventario.services import registrar_devolucion_colegio
from logistica.inventario.tests.utils import crear_material
from usuarios.models import ModuloUsuario

XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def _filas_xlsx(response):
    ws = load_workbook(io.BytesIO(response.content)).active
    return list(ws.iter_rows(min_row=2, values_only=True))


class _BaseFinDevolucionesTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='financiera.testserver')
        self.user = User.objects.create_user(username='finan', password='pass')
        self.user.groups.add(Group.objects.get(name=GRUPO_STAFF_FINANCIERA))
        self.client.login(username='finan', password='pass')

        # Quien registra la devolución es logística; financiera solo consulta.
        self.logis = User.objects.create_user(username='logis', password='pass')
        self.logis.groups.add(Group.objects.get(name=GRUPO_STAFF_LOGISTICA))

        self.categoria = Categoria.objects.create(nombre='Simulacros')
        self.bodega = Bodega.objects.create(nombre='Principal')
        self.material = crear_material(categoria=self.categoria,
                                       referencia='Cuadernillo A')

    def _registrar(self, **kw):
        datos = {'fecha_recibido': date(2026, 7, 20), 'colegio': 'Colegio Norte',
                 'codigo_colegio': 'C-01', 'regional': 'Nororiente',
                 'ejecutivo': 'Ana Ruiz', 'observaciones': 'Sobrantes'}
        lineas = kw.pop('lineas', [(self.material[3], 5), (self.material[4], 2)])
        datos.update(kw)
        return registrar_devolucion_colegio(bodega=self.bodega, lineas=lineas,
                                            usuario=self.logis, **datos)


class GatesFinDevolucionesTest(_BaseFinDevolucionesTest):

    def test_anonimo_redirigido(self):
        c = Client(HTTP_HOST='financiera.testserver')
        self.assertEqual(c.get('/devoluciones/').status_code, 302)

    def test_usuario_de_otra_area_no_entra(self):
        c = Client(HTTP_HOST='financiera.testserver')
        c.login(username='logis', password='pass')
        self.assertEqual(c.get('/devoluciones/').status_code, 302)

    def test_staff_financiera_ve_la_lista(self):
        self._registrar()
        resp = self.client.get('/devoluciones/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Colegio Norte')

    def test_menu_muestra_el_item(self):
        html = self.client.get('/devoluciones/').content.decode()
        self.assertIn('Devoluciones', html)

    def test_lectura_ve_y_exporta(self):
        """Sin escrituras en el área, LECTURA se comporta como COMPLETO."""
        ModuloUsuario.objects.create(user=self.user, area='financiera',
                                     modulo='devoluciones',
                                     nivel=ModuloUsuario.Nivel.LECTURA)
        self.assertEqual(self.client.get('/devoluciones/').status_code, 200)
        resp = self.client.post('/devoluciones/exportar/', {})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], XLSX_MIME)

    def test_sin_acceso_al_modulo_no_entra(self):
        ModuloUsuario.objects.create(user=self.user, area='financiera',
                                     modulo='devoluciones',
                                     nivel=ModuloUsuario.Nivel.SIN_ACCESO)
        self.assertEqual(self.client.get('/devoluciones/').status_code, 302)


class SoloLecturaTest(_BaseFinDevolucionesTest):

    def test_no_hay_rutas_de_escritura(self):
        """Registrar es competencia de logística: las rutas de alta y detalle
        del otro subdominio no existen en financiera."""
        for url in ['/devoluciones/nueva/', '/devoluciones/1/']:
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_lista_no_pinta_acciones_de_escritura(self):
        self._registrar()
        html = self.client.get('/devoluciones/').content.decode()
        self.assertNotIn('Nueva devolución', html)
        self.assertIn('solo lectura', html)

    def test_lista_es_get_only(self):
        self.assertEqual(self.client.post('/devoluciones/', {}).status_code, 405)


class ExportFinDevolucionesTest(_BaseFinDevolucionesTest):

    def test_mismo_layout_que_logistica(self):
        from logistica.devoluciones.export import COLUMNAS

        self._registrar()
        resp = self.client.post('/devoluciones/exportar/', {})
        ws = load_workbook(io.BytesIO(resp.content)).active
        cabeceras = list(next(ws.iter_rows(min_row=1, max_row=1, values_only=True)))
        self.assertEqual(cabeceras, COLUMNAS)

        fila = _filas_xlsx(resp)[0]
        self.assertEqual(fila[0], '20/07/2026')
        self.assertEqual(fila[1], 'Colegio Norte')
        self.assertEqual(fila[6], 'Cuadernillo A')
        self.assertEqual(fila[7 + 3], 5)
        self.assertEqual(fila[19], 7)
        self.assertEqual(fila[20], 'Válida')

    def test_filtros_de_fecha_y_colegio(self):
        self._registrar(colegio='Colegio Norte', fecha_recibido=date(2026, 7, 1),
                        lineas=[(self.material[0], 1)])
        self._registrar(colegio='Colegio Sur', fecha_recibido=date(2026, 7, 20),
                        lineas=[(self.material[1], 1)])

        filas = _filas_xlsx(self.client.post('/devoluciones/exportar/',
                                             {'desde': '2026-07-10'}))
        self.assertEqual([f[1] for f in filas], ['Colegio Sur'])

        filas = _filas_xlsx(self.client.post('/devoluciones/exportar/',
                                             {'colegio': 'norte'}))
        self.assertEqual([f[1] for f in filas], ['Colegio Norte'])

    def test_get_no_permitido(self):
        self.assertEqual(self.client.get('/devoluciones/exportar/').status_code,
                         405)


class DetalleEnPantallaTest(_BaseFinDevolucionesTest):
    """Financiera ve TODO el detalle sin bajar el Excel (misma tabla que logística)."""

    def test_detalle_por_material(self):
        self._registrar(lineas=[(self.material[3], 5), (self.material[4], 2)])
        resp = self.client.get('/devoluciones/detalle/')
        self.assertEqual(resp.status_code, 200)
        fila = resp.context['filas'][0]
        self.assertEqual(fila['celdas'][3]['cantidad'], 5)
        self.assertEqual(fila['total'], 7)
        for texto in ['Cuadernillo A', 'Colegio Norte', 'Ana Ruiz']:
            self.assertContains(resp, texto)

    def test_marca_las_no_validas(self):
        self._registrar(colegio='Colegio Sur', lineas=[(self.material[0], 1)],
                        valida=False, motivo_no_valida='Cuadernillos rayados')
        resp = self.client.get('/devoluciones/detalle/')
        self.assertContains(resp, 'No válida')
        self.assertContains(resp, 'Cuadernillos rayados')

    def test_sigue_siendo_solo_lectura(self):
        self.assertEqual(self.client.post('/devoluciones/detalle/', {}).status_code,
                         405)
        # No enlaza la vista de devolución de logística (aquí no existe).
        self._registrar()
        html = self.client.get('/devoluciones/detalle/').content.decode()
        self.assertNotIn('Nueva devolución', html)

    def test_gate_de_area(self):
        c = Client(HTTP_HOST='financiera.testserver')
        self.assertEqual(c.get('/devoluciones/detalle/').status_code, 302)
        c.login(username='logis', password='pass')
        self.assertEqual(c.get('/devoluciones/detalle/').status_code, 302)
