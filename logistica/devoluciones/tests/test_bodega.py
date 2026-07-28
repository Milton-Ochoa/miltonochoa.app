"""Restricción por bodega en el alta de devoluciones de colegio (Fase 2).

Vive aquí y no en `logistica/inventario/tests/` porque el form y la vista del
alta son de esta sub-app; el dominio (servicio y modelos) sigue en inventario.
Las dos barreras: `<select>` recortado y POST forjado que no debe escribir nada
—ni la cabecera, ni el ledger, ni el stock—.

Paquete `tests/` → imports absolutos (regla de CLAUDE.md).
"""
from django.contrib.auth.models import Group, User
from django.test import Client, TestCase

from core.areas import GRUPO_STAFF_LOGISTICA
from logistica.inventario.models import (Bodega, BodegaUsuario, Categoria,
                                         DevolucionColegio, Movimiento, Stock)
from logistica.inventario.tests.utils import crear_material, lineas_post


class _BaseDevolucionBodegaTest(TestCase):

    asignar = True
    superusuario = False

    def setUp(self):
        self.client = Client(HTTP_HOST='logistica.testserver')
        if self.superusuario:
            self.user = User.objects.create_superuser(username='logis',
                                                      password='pass')
        else:
            self.user = User.objects.create_user(username='logis',
                                                 password='pass')
            self.user.groups.add(Group.objects.get(name=GRUPO_STAFF_LOGISTICA))
        self.client.login(username='logis', password='pass')

        self.propia = Bodega.objects.create(nombre='Principal')
        self.ajena = Bodega.objects.create(nombre='Sucursal')
        if self.asignar:
            BodegaUsuario.objects.create(usuario=self.user, bodega=self.propia)

        self.categoria = Categoria.objects.create(nombre='Simulacros')
        self.material = crear_material(categoria=self.categoria,
                                       referencia='Cuadernillo A')

    def _mensajes(self, response):
        return [str(m) for m in response.context['messages']]

    def _stock(self, bodega, grado=3):
        fila = Stock.objects.filter(item=self.material[grado],
                                    bodega=bodega).first()
        return fila.cantidad if fila else 0

    def _post(self, bodega, cantidad=4, grado=3):
        datos = {
            'fecha_recibido': '2026-07-20',
            'colegio': 'Colegio Norte',
            'codigo_colegio': '', 'regional': '', 'ejecutivo': '',
            'bodega': bodega.pk, 'observaciones': '',
            **lineas_post([(self.material, {grado: cantidad})]),
        }
        return self.client.post('/devoluciones/nueva/', datos)


class DevolucionColegioRestringidaTest(_BaseDevolucionBodegaTest):

    def test_select_solo_ofrece_su_bodega(self):
        r = self.client.get('/devoluciones/nueva/')
        campo = r.context['form'].fields['bodega']
        self.assertEqual(list(campo.queryset), [self.propia])
        self.assertIsNone(campo.empty_label)

    def test_devolucion_a_su_bodega(self):
        r = self._post(self.propia)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(DevolucionColegio.objects.count(), 1)
        self.assertEqual(self._stock(self.propia), 4)

    def test_post_forjado_a_bodega_ajena_no_escribe(self):
        r = self._post(self.ajena)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(DevolucionColegio.objects.count(), 0)
        self.assertEqual(Movimiento.objects.count(), 0)
        self.assertEqual(self._stock(self.ajena), 0)
        self.assertTrue(any('Principal' in m for m in self._mensajes(r)),
                        self._mensajes(r))

    def test_el_re_render_conserva_las_lineas(self):
        r = self._post(self.ajena, cantidad=9)
        celdas = r.context['lineas_previas'][0]['celdas']
        self.assertEqual([c['valor'] for c in celdas if c['valor']], ['9'])


class DevolucionSinAsignacionTest(_BaseDevolucionBodegaTest):
    """Retrocompatibilidad: sin fila se registra en cualquier bodega."""

    asignar = False

    def test_registra_en_bodega_ajena(self):
        r = self._post(self.ajena)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self._stock(self.ajena), 4)


class DevolucionSuperusuarioTest(_BaseDevolucionBodegaTest):

    superusuario = True

    def test_superusuario_con_asignacion_registra_en_la_ajena(self):
        r = self._post(self.ajena)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self._stock(self.ajena), 4)
