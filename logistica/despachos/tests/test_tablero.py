"""Tests del tablero (`/despachos/`) y el detalle (`/despachos/orden/<pk>/`).

Cubren: gates de área + enforcement granular (LECTURA puede VER el tablero),
contenido por tab (por despachar / despachadas sin remisión / cerradas), la
exclusión de órdenes 100% FORMACIÓN, el rango server de las cerradas, el salto
rápido `?q=` y el detalle con líneas de material / formación / eventos.

Arnés `Client(HTTP_HOST='logistica.testserver')`. Las órdenes se crean por ORM
directo (no por import) para controlar cada estado con precisión.
"""
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import Client, TestCase
from django.utils import timezone

from core.areas import GRUPO_STAFF_FINANCIERA, GRUPO_STAFF_LOGISTICA

from logistica.despachos.models import (EventoOrden, LineaOrden, OrdenDespacho)
from usuarios.models import ModuloUsuario

_TABLERO = '/despachos/'


def _orden(id_orden, *, estado=OrdenDespacho.Estado.PENDIENTE, es_despachable=True,
           fecha_entrega=None, fecha_orden=None, resumen='2× 727', **kw):
    return OrdenDespacho.objects.create(
        id_orden=id_orden, estado=estado, es_despachable=es_despachable,
        fecha_entrega=fecha_entrega, fecha_orden=fecha_orden,
        resumen_articulos=resumen, cliente=kw.pop('cliente', 'Colegio X'),
        bodega=kw.pop('bodega', 'BUCARAMANGA'), ciudad=kw.pop('ciudad', 'Bucaramanga'),
        departamento=kw.pop('departamento', 'Santander'), **kw)


def _aware(y, m, d, hh=10, mm=0):
    return timezone.make_aware(datetime(y, m, d, hh, mm),
                               timezone.get_default_timezone())


class _BaseLogistica(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST='logistica.testserver')
        self.user = User.objects.create_user(username='logis', password='pass')
        self.user.groups.add(Group.objects.get(name=GRUPO_STAFF_LOGISTICA))
        self.client.login(username='logis', password='pass')


class GatesTest(_BaseLogistica):
    def test_anonimo_redirigido(self):
        c = Client(HTTP_HOST='logistica.testserver')
        self.assertEqual(c.get(_TABLERO).status_code, 302)

    def test_otra_area_no_entra(self):
        u = User.objects.create_user(username='finan', password='pass')
        u.groups.add(Group.objects.get(name=GRUPO_STAFF_FINANCIERA))
        c = Client(HTTP_HOST='logistica.testserver')
        c.login(username='finan', password='pass')
        self.assertEqual(c.get(_TABLERO).status_code, 302)

    def test_staff_ve_el_tablero(self):
        self.assertEqual(self.client.get(_TABLERO).status_code, 200)

    def test_lectura_puede_ver_el_tablero(self):
        # El tablero es un GET → LECTURA lo deja pasar (solo las escrituras se bloquean).
        ModuloUsuario.objects.create(user=self.user, area='logistica',
                                     modulo='despachos',
                                     nivel=ModuloUsuario.Nivel.LECTURA)
        self.assertEqual(self.client.get(_TABLERO).status_code, 200)


class TabsTest(_BaseLogistica):
    def setUp(self):
        super().setUp()
        self.o_pendiente = _orden('PPAL-1', estado=OrdenDespacho.Estado.PENDIENTE)
        self.o_alistada = _orden('PPAL-2', estado=OrdenDespacho.Estado.ALISTADA)
        self.o_despachada = _orden('PPAL-3', estado=OrdenDespacho.Estado.DESPACHADA)
        self.o_remitida = _orden('PPAL-4', estado=OrdenDespacho.Estado.REMITIDA,
                                 fecha_orden=_aware(2026, 7, 15))
        self.o_anulada = _orden('PPAL-5', estado=OrdenDespacho.Estado.ANULADA,
                                fecha_orden=_aware(2026, 7, 16))
        # 100% FORMACIÓN → no despachable, pero SÍ aparece en "abiertas".
        self.o_formacion = _orden('PPAL-6', estado=OrdenDespacho.Estado.PENDIENTE,
                                  es_despachable=False, resumen='5× HORAS CLASE')

    def test_abiertas_incluye_las_no_despachables(self):
        ordenes = self.client.get(_TABLERO + '?tab=abiertas').context['ordenes']
        ids = {o.id_orden for o in ordenes}
        self.assertEqual(ids, {'PPAL-1', 'PPAL-2', 'PPAL-6'})

    def test_abiertas_es_el_default(self):
        r1 = self.client.get(_TABLERO)
        self.assertEqual(r1.context['tab'], 'abiertas')
        # tab desconocida cae en abiertas.
        r2 = self.client.get(_TABLERO + '?tab=inventada')
        self.assertEqual(r2.context['tab'], 'abiertas')

    def test_sin_remision_solo_despachadas(self):
        ordenes = self.client.get(_TABLERO + '?tab=sin_remision').context['ordenes']
        self.assertEqual({o.id_orden for o in ordenes}, {'PPAL-3'})

    def test_cerradas_terminales_en_rango(self):
        ordenes = self.client.get(
            _TABLERO + '?tab=cerradas&desde=2026-07-01&hasta=2026-07-31').context['ordenes']
        self.assertEqual({o.id_orden for o in ordenes}, {'PPAL-4', 'PPAL-5'})

    def test_cerradas_respeta_el_rango(self):
        # Un rango que no cubre las fechas de orden → vacío.
        ordenes = self.client.get(
            _TABLERO + '?tab=cerradas&desde=2026-01-01&hasta=2026-01-31').context['ordenes']
        self.assertEqual(list(ordenes), [])

    def test_contadores_por_tab(self):
        ctx = self.client.get(_TABLERO).context
        # El contador de la tab espeja lo que se lista (incluida PPAL-6).
        self.assertEqual(ctx['n_abiertas'], 3)
        self.assertEqual(ctx['n_sin_remision'], 1)


class ResaltadoTest(_BaseLogistica):
    """Una orden 100% FORMACIÓN se ve en el tablero, pero no alerta por
    vencimiento: no hay material que despachar."""

    def setUp(self):
        super().setUp()
        ayer = timezone.localdate() - timedelta(days=1)
        _orden('PPAL-20', fecha_entrega=ayer)
        _orden('PPAL-21', fecha_entrega=ayer, es_despachable=False,
               resumen='5× HORAS CLASE')

    def test_solo_la_despachable_se_resalta(self):
        html = self.client.get(_TABLERO).content.decode()
        # Una sola fila roja (la despachable vencida); la otra se lista sin marca.
        self.assertEqual(html.count('class="fila-orden fila-vencida"'), 1)
        self.assertIn('PPAL-21', html)

    def test_los_nombres_de_articulo_van_en_la_fila(self):
        # `data-artnombres` alimenta el filtro tipo Excel de la columna.
        html = self.client.get(_TABLERO).content.decode()
        self.assertIn('data-artnombres="HORAS CLASE"', html)


class SaltoRapidoTest(_BaseLogistica):
    def setUp(self):
        super().setUp()
        self.orden = _orden('PPAL-77')

    def test_q_exacto_redirige_al_detalle(self):
        resp = self.client.get(_TABLERO + '?q=PPAL-77')
        self.assertRedirects(resp, f'/despachos/orden/{self.orden.pk}/')

    def test_q_sin_prefijo_encuentra(self):
        resp = self.client.get(_TABLERO + '?q=77')
        self.assertRedirects(resp, f'/despachos/orden/{self.orden.pk}/')

    def test_q_inexistente_avisa(self):
        resp = self.client.get(_TABLERO + '?q=PPAL-999')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any('999' in str(m) for m in resp.context['messages']))


class DetalleTest(_BaseLogistica):
    def setUp(self):
        super().setUp()
        self.orden = _orden('PPAL-100')
        # Mixta: 1 línea de material (EVALUACIÓN) + 1 de formación.
        LineaOrden.objects.create(orden=self.orden, cod_articulo='727',
                                  descripcion='SIM-1', categoria='EVALUACIÓN',
                                  cantidad=Decimal('2'), es_material=True, orden_archivo=0)
        LineaOrden.objects.create(orden=self.orden, cod_articulo='HC',
                                  descripcion='HORAS CLASE', categoria='FORMACIÓN',
                                  cantidad=Decimal('5'), es_material=False, orden_archivo=1)
        EventoOrden.objects.create(orden=self.orden,
                                   tipo=EventoOrden.Tipo.ALERTA_REMISION,
                                   detalle='Falta remisión', usuario=None)

    def test_detalle_separa_material_y_formacion(self):
        ctx = self.client.get(f'/despachos/orden/{self.orden.pk}/').context
        self.assertEqual([l.cod_articulo for l in ctx['lineas_material']], ['727'])
        self.assertEqual([l.cod_articulo for l in ctx['lineas_formacion']], ['HC'])

    def test_detalle_muestra_eventos(self):
        ctx = self.client.get(f'/despachos/orden/{self.orden.pk}/').context
        self.assertEqual(len(ctx['eventos']), 1)

    def test_detalle_404_si_no_existe(self):
        self.assertEqual(self.client.get('/despachos/orden/999999/').status_code, 404)
