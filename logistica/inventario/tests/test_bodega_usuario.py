"""Tests de la restricción de escritura por bodega.

Fase 1 — el modelo `BodegaUsuario`, los helpers de `permisos.py` y la página de
asignación. Lo que se blinda es la semántica del helper (sobre todo los dos
casos que mantienen verde el resto de la suite: **sin fila = sin restricción** y
**superusuario nunca restringido**) y el gate de la página.

Fase 2 — los documentos con form de cabecera: entrada, salida, traslado (solo el
ORIGEN se restringe) y devolución de colegio (esta última en
`logistica/devoluciones/tests/test_bodega.py`, junto a su sub-app). Cada camino
se prueba por sus dos barreras: el `<select>` recortado y el POST **forjado**
con la bodega ajena, que no debe escribir nada.

Fase 3 — las escrituras SIN form de cabecera: préstamos (bodega por línea),
devolución de préstamo (rechazo total si hay líneas mixtas), ajuste manual y
adjuntos de entrada. Aquí vive además `LecturaGlobalTest`, el guardián de que
nadie scopee por bodega los querysets de LECTURA.

Mismo arnés que el resto del área: `Client(HTTP_HOST='logistica.testserver')`.
"""
import shutil
import tempfile
from datetime import date

from django.contrib.auth.models import AnonymousUser, Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import ProtectedError
from django.test import Client, TestCase, override_settings

from core.areas import GRUPO_STAFF_FINANCIERA, GRUPO_STAFF_LOGISTICA

from logistica.inventario.models import (AdjuntoEntrada, Bodega, BodegaUsuario,
                                         Categoria, Devolucion, Entrada,
                                         Movimiento, Prestamo, Salida, Stock,
                                         Tercero, Traslado)
from logistica.inventario.permisos import (BodegaNoPermitida, bodega_asignada,
                                           bodegas_escribibles, es_restringido,
                                           exigir_bodega, exigir_bodegas,
                                           puede_escribir_en)
from logistica.inventario.services import crear_prestamo, registrar_entrada
from logistica.inventario.tests.utils import crear_material, lineas_post

# Los adjuntos van a disco local (nunca a Supabase), patrón `test_movimientos`.
_STORAGE_LOCAL = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
_MEDIA_TMP = tempfile.mkdtemp()


class _BaseBodegaUsuarioTest(TestCase):
    """Staff de logística logueado + dos bodegas (la suya y la ajena)."""

    def setUp(self):
        self.client = Client(HTTP_HOST='logistica.testserver')
        self.user = User.objects.create_user(username='logis', password='pass')
        self.user.groups.add(Group.objects.get(name=GRUPO_STAFF_LOGISTICA))
        self.client.login(username='logis', password='pass')
        self.propia = Bodega.objects.create(nombre='Principal')
        self.ajena = Bodega.objects.create(nombre='Sucursal')

    def _asignar(self, bodega=None, usuario=None):
        return BodegaUsuario.objects.create(usuario=usuario or self.user,
                                            bodega=bodega or self.propia)

    def _mensajes(self, response):
        return [str(m) for m in response.context['messages']]

    def _recargar(self, usuario=None):
        """Un `User` recién leído: el helper memoiza en el objeto, así que tras
        cambiar la asignación hay que releerlo (igual que en un request nuevo)."""
        return User.objects.get(pk=(usuario or self.user).pk)


class HelperBodegaUsuarioTest(_BaseBodegaUsuarioTest):

    def test_sin_asignacion_no_hay_restriccion(self):
        """El caso que mantiene verde toda la suite existente."""
        self.assertIsNone(bodega_asignada(self.user))
        self.assertFalse(es_restringido(self.user))
        self.assertTrue(puede_escribir_en(self.user, self.propia))
        self.assertTrue(puede_escribir_en(self.user, self.ajena))
        self.assertEqual(bodegas_escribibles(self.user).count(), 2)

    def test_con_asignacion_solo_su_bodega(self):
        self._asignar()
        user = self._recargar()
        self.assertEqual(bodega_asignada(user), self.propia)
        self.assertTrue(es_restringido(user))
        self.assertTrue(puede_escribir_en(user, self.propia))
        self.assertFalse(puede_escribir_en(user, self.ajena))
        self.assertEqual(list(bodegas_escribibles(user)), [self.propia])

    def test_superusuario_con_asignacion_no_se_restringe(self):
        """Caso trampa: tiene fila, pero es superusuario."""
        admin = User.objects.create_superuser(username='admin', password='pass')
        self._asignar(usuario=admin)
        admin = self._recargar(admin)
        self.assertFalse(es_restringido(admin))
        self.assertTrue(puede_escribir_en(admin, self.ajena))
        self.assertEqual(bodegas_escribibles(admin).count(), 2)

    def test_anonimo_y_none_no_revientan(self):
        for sujeto in (None, AnonymousUser()):
            self.assertIsNone(bodega_asignada(sujeto))
            self.assertFalse(es_restringido(sujeto))
            self.assertTrue(puede_escribir_en(sujeto, self.ajena))

    def test_bodega_inactiva_asignada_sigue_siendo_la_suya(self):
        """`bodegas_escribibles` no filtra por `activa`: quien consume decide,
        para poder decir "tu bodega está inactiva" en vez de "no puedes escribir"."""
        self.propia.activa = False
        self.propia.save(update_fields=['activa'])
        self._asignar()
        user = self._recargar()
        self.assertEqual(list(bodegas_escribibles(user)), [self.propia])

    def test_exigir_bodega_lanza_con_ambos_nombres(self):
        self._asignar()
        user = self._recargar()
        exigir_bodega(user, self.propia)  # no lanza
        with self.assertRaises(BodegaNoPermitida) as ctx:
            exigir_bodega(user, self.ajena)
        mensaje = str(ctx.exception)
        self.assertIn('Sucursal', mensaje)
        self.assertIn('Principal', mensaje)

    def test_exigir_bodega_accion_personalizada(self):
        self._asignar()
        with self.assertRaises(BodegaNoPermitida) as ctx:
            exigir_bodega(self._recargar(), self.ajena, accion='trasladar desde')
        self.assertIn('trasladar desde', str(ctx.exception))

    def test_exigir_bodegas_lanza_en_la_primera_ajena(self):
        self._asignar()
        user = self._recargar()
        exigir_bodegas(user, [self.propia, self.propia])  # no lanza
        with self.assertRaises(BodegaNoPermitida):
            exigir_bodegas(user, [self.propia, self.ajena])

    def test_una_bodega_por_usuario(self):
        self._asignar()
        BodegaUsuario.objects.update_or_create(
            usuario=self.user, defaults={'bodega': self.ajena})
        self.assertEqual(BodegaUsuario.objects.filter(usuario=self.user).count(), 1)
        self.assertEqual(bodega_asignada(self._recargar()), self.ajena)

    def test_borrar_bodega_asignada_esta_protegido(self):
        """PROTECT: si el borrado arrastrara la asignación, el usuario ganaría
        acceso global en silencio."""
        self._asignar()
        with self.assertRaises(ProtectedError):
            self.propia.delete()

    def test_borrar_usuario_arrastra_su_asignacion(self):
        otro = User.objects.create_user(username='otro', password='pass')
        self._asignar(usuario=otro)
        otro.delete()
        self.assertEqual(BodegaUsuario.objects.count(), 0)


class GuardDesactivarBodegaAsignadaTest(_BaseBodegaUsuarioTest):

    def test_no_desactiva_bodega_con_usuarios_asignados(self):
        self._asignar()
        r = self.client.post('/catalogos/bodegas/',
                             {'accion': 'toggle', 'bodega_id': self.propia.pk},
                             follow=True)
        self.propia.refresh_from_db()
        self.assertTrue(self.propia.activa)
        mensajes = self._mensajes(r)
        self.assertTrue(any('está asignada' in m for m in mensajes), mensajes)
        self.assertTrue(any('logis' in m for m in mensajes), mensajes)

    def test_sin_asignados_se_desactiva_normal(self):
        r = self.client.post('/catalogos/bodegas/',
                             {'accion': 'toggle', 'bodega_id': self.ajena.pk},
                             follow=True)
        self.ajena.refresh_from_db()
        self.assertFalse(self.ajena.activa)
        self.assertTrue(any('desactivada' in m for m in self._mensajes(r)))


class BodegasUsuariosGateTest(TestCase):
    """Patrón GatesXTest: la página es solo del superusuario."""

    URL = '/catalogos/bodegas/usuarios/'

    def test_anonimo_redirigido(self):
        c = Client(HTTP_HOST='logistica.testserver')
        self.assertEqual(c.get(self.URL).status_code, 302)

    def test_usuario_de_otra_area_no_entra(self):
        u = User.objects.create_user(username='finan', password='pass')
        u.groups.add(Group.objects.get(name=GRUPO_STAFF_FINANCIERA))
        c = Client(HTTP_HOST='logistica.testserver')
        c.login(username='finan', password='pass')
        self.assertEqual(c.get(self.URL).status_code, 302)

    def test_staff_logistica_no_superusuario_es_rechazado(self):
        u = User.objects.create_user(username='logis', password='pass')
        u.groups.add(Group.objects.get(name=GRUPO_STAFF_LOGISTICA))
        c = Client(HTTP_HOST='logistica.testserver')
        c.login(username='logis', password='pass')
        r = c.get(self.URL, follow=True)
        self.assertTrue(any('Solo el administrador' in str(m)
                            for m in r.context['messages']))

    def test_superusuario_entra(self):
        User.objects.create_superuser(username='admin', password='pass')
        c = Client(HTTP_HOST='logistica.testserver')
        c.login(username='admin', password='pass')
        self.assertEqual(c.get(self.URL).status_code, 200)


class BodegasUsuariosPaginaTest(TestCase):

    URL = '/catalogos/bodegas/usuarios/'

    def setUp(self):
        self.client = Client(HTTP_HOST='logistica.testserver')
        User.objects.create_superuser(username='admin', password='pass')
        self.client.login(username='admin', password='pass')
        self.staff = User.objects.create_user(username='logis', password='pass')
        self.staff.groups.add(Group.objects.get(name=GRUPO_STAFF_LOGISTICA))
        self.propia = Bodega.objects.create(nombre='Principal')
        self.ajena = Bodega.objects.create(nombre='Sucursal')

    def test_lista_solo_usuarios_del_area_sin_superusuarios(self):
        r = self.client.get(self.URL)
        usuarios = list(r.context['usuarios'])
        self.assertEqual([u.username for u in usuarios], ['logis'])

    def test_select_solo_ofrece_bodegas_activas(self):
        self.ajena.activa = False
        self.ajena.save(update_fields=['activa'])
        r = self.client.get(self.URL)
        self.assertEqual([b.nombre for b in r.context['bodegas']], ['Principal'])

    def test_asignar_crea_la_fila(self):
        r = self.client.post(self.URL,
                             {'user_id': self.staff.pk, 'bodega_id': self.propia.pk},
                             follow=True)
        fila = BodegaUsuario.objects.get(usuario=self.staff)
        self.assertEqual(fila.bodega, self.propia)
        self.assertEqual(fila.asignado_por.username, 'admin')
        self.assertTrue(any('Principal' in m for m in
                            [str(x) for x in r.context['messages']]))

    def test_reasignar_no_duplica(self):
        self.client.post(self.URL,
                         {'user_id': self.staff.pk, 'bodega_id': self.propia.pk})
        self.client.post(self.URL,
                         {'user_id': self.staff.pk, 'bodega_id': self.ajena.pk})
        self.assertEqual(BodegaUsuario.objects.filter(usuario=self.staff).count(), 1)
        self.assertEqual(BodegaUsuario.objects.get(usuario=self.staff).bodega,
                         self.ajena)

    def test_bodega_vacia_borra_la_asignacion(self):
        BodegaUsuario.objects.create(usuario=self.staff, bodega=self.propia)
        self.client.post(self.URL, {'user_id': self.staff.pk, 'bodega_id': ''})
        self.assertFalse(BodegaUsuario.objects.filter(usuario=self.staff).exists())

    def test_bodega_inactiva_no_se_puede_asignar(self):
        self.propia.activa = False
        self.propia.save(update_fields=['activa'])
        r = self.client.post(self.URL,
                             {'user_id': self.staff.pk, 'bodega_id': self.propia.pk})
        self.assertEqual(r.status_code, 404)
        self.assertFalse(BodegaUsuario.objects.exists())

    def test_post_de_no_superusuario_no_crea_fila(self):
        c = Client(HTTP_HOST='logistica.testserver')
        c.login(username='logis', password='pass')
        c.post(self.URL, {'user_id': self.staff.pk, 'bodega_id': self.propia.pk})
        self.assertFalse(BodegaUsuario.objects.exists())

    def test_enlace_a_la_pagina_solo_para_superusuario(self):
        r = self.client.get('/catalogos/bodegas/')
        self.assertContains(r, self.URL)

        c = Client(HTTP_HOST='logistica.testserver')
        c.login(username='logis', password='pass')
        self.assertNotContains(c.get('/catalogos/bodegas/'), self.URL)


# ---------------------------------------------------------------------------
# Fase 2 — documentos con form de cabecera
# ---------------------------------------------------------------------------

class _BaseDocumentosTest(TestCase):
    """Staff de logística + dos bodegas + un material completo (12 grados).

    Los flags de clase dejan reusar el mismo arnés para los tres escenarios:
    restringido (default), sin asignación (retrocompatibilidad) y superusuario
    con asignación.
    """

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

        self.categoria = Categoria.objects.create(nombre='Papelería')
        self.material = crear_material(categoria=self.categoria,
                                       referencia='Cuadernillo')
        self.tercero = Tercero.objects.create(nombre='Colegio X')

    # -- helpers ------------------------------------------------------------

    def _mensajes(self, response):
        return [str(m) for m in response.context['messages']]

    def _lineas(self, cantidad=2, grado=3):
        return lineas_post([(self.material, {grado: cantidad})])

    def _sembrar(self, bodega, cantidad=10, grado=3):
        """Siempre por servicio, nunca tocando `Stock` a mano."""
        registrar_entrada(bodega=bodega, lineas=[(self.material[grado], cantidad)],
                          usuario=self.user)

    def _stock(self, bodega, grado=3):
        fila = Stock.objects.filter(item=self.material[grado],
                                    bodega=bodega).first()
        return fila.cantidad if fila else 0

    def _post_entrada(self, bodega, **kw):
        datos = {'bodega': bodega.pk, 'proveedor': '', 'observaciones': '',
                 **self._lineas(**kw)}
        return self.client.post('/entradas/nueva/', datos)

    def _post_salida(self, bodega, **kw):
        datos = {'bodega': bodega.pk, 'tercero': '', 'motivo': 'Consumo',
                 'observaciones': '', **self._lineas(**kw)}
        return self.client.post('/salidas/nueva/', datos)

    def _post_traslado(self, origen, destino, **kw):
        datos = {'bodega_origen': origen.pk, 'bodega_destino': destino.pk,
                 'observaciones': '', **self._lineas(**kw)}
        return self.client.post('/traslados/nuevo/', datos)

    def _post_prestamo(self, bodega, cantidad=2, grado=3,
                       direccion=Prestamo.Direccion.OTORGADO):
        datos = {'direccion': direccion, 'tercero': self.tercero.pk,
                 'fecha_compromiso': '2030-01-01', 'observaciones': '',
                 **lineas_post([(self.material, bodega, {grado: cantidad})],
                               con_bodega=True)}
        return self.client.post('/prestamos/nuevo/', datos)

    def _post_ajuste(self, bodega, nueva_cantidad, grado=3):
        return self.client.post('/ajustes/nuevo/', {
            'item_id': self.material[grado].pk, 'bodega_id': bodega.pk,
            'nueva_cantidad': nueva_cantidad, 'motivo': 'Conteo físico',
        }, follow=True)


class EntradaRestringidaTest(_BaseDocumentosTest):

    def test_select_solo_ofrece_su_bodega(self):
        r = self.client.get('/entradas/nueva/')
        campo = r.context['form'].fields['bodega']
        self.assertEqual(list(campo.queryset), [self.propia])
        # Una sola opción → preseleccionada y sin placeholder.
        self.assertIsNone(campo.empty_label)

    def test_entrada_en_su_bodega(self):
        r = self._post_entrada(self.propia)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Entrada.objects.count(), 1)
        self.assertEqual(self._stock(self.propia), 2)

    def test_post_forjado_a_bodega_ajena_no_escribe(self):
        r = self._post_entrada(self.ajena)
        self.assertEqual(r.status_code, 200)  # re-render, sin redirect
        self.assertEqual(Entrada.objects.count(), 0)
        self.assertEqual(Movimiento.objects.count(), 0)
        self.assertEqual(self._stock(self.ajena), 0)
        self.assertTrue(any('Principal' in m for m in self._mensajes(r)),
                        self._mensajes(r))

    def test_el_re_render_conserva_las_lineas(self):
        r = self._post_entrada(self.ajena, cantidad=7)
        celdas = r.context['lineas_previas'][0]['celdas']
        self.assertEqual([c['valor'] for c in celdas if c['valor']], ['7'])


class SalidaRestringidaTest(_BaseDocumentosTest):

    def test_select_solo_ofrece_su_bodega(self):
        r = self.client.get('/salidas/nueva/')
        self.assertEqual(list(r.context['form'].fields['bodega'].queryset),
                         [self.propia])

    def test_salida_de_su_bodega(self):
        self._sembrar(self.propia)
        r = self._post_salida(self.propia)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Salida.objects.count(), 1)
        self.assertEqual(self._stock(self.propia), 8)

    def test_post_forjado_a_bodega_ajena_no_descuenta(self):
        self._sembrar(self.ajena)
        r = self._post_salida(self.ajena)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Salida.objects.count(), 0)
        self.assertEqual(self._stock(self.ajena), 10)  # intacto
        self.assertTrue(any('Principal' in m for m in self._mensajes(r)))


class TrasladoRestringidoTest(_BaseDocumentosTest):

    def test_solo_el_origen_se_restringe(self):
        r = self.client.get('/traslados/nuevo/')
        campos = r.context['form'].fields
        self.assertEqual(list(campos['bodega_origen'].queryset), [self.propia])
        self.assertEqual(campos['bodega_destino'].queryset.count(), 2)

    def test_desde_la_suya_hacia_la_ajena_pasa(self):
        """La operación real: sacar material de su sede hacia otra."""
        self._sembrar(self.propia)
        r = self._post_traslado(self.propia, self.ajena)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Traslado.objects.count(), 1)
        self.assertEqual(self._stock(self.propia), 8)
        self.assertEqual(self._stock(self.ajena), 2)

    def test_desde_la_ajena_se_rechaza(self):
        self._sembrar(self.ajena)
        r = self._post_traslado(self.ajena, self.propia)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Traslado.objects.count(), 0)
        self.assertEqual(self._stock(self.ajena), 10)
        self.assertEqual(self._stock(self.propia), 0)
        self.assertTrue(any('trasladar DESDE tu bodega' in m
                            for m in self._mensajes(r)), self._mensajes(r))


class SinAsignacionRetrocompatTest(_BaseDocumentosTest):
    """El guardián del baseline: sin fila, todo funciona como siempre."""

    asignar = False

    def test_escribe_en_cualquier_bodega(self):
        self._post_entrada(self.ajena)
        self.assertEqual(self._stock(self.ajena), 2)
        self._post_salida(self.ajena, cantidad=1)
        self.assertEqual(self._stock(self.ajena), 1)
        self._post_traslado(self.ajena, self.propia, cantidad=1)
        self.assertEqual(self._stock(self.propia), 1)
        self.assertEqual(Traslado.objects.count(), 1)

    def test_los_selects_ofrecen_todas(self):
        r = self.client.get('/entradas/nueva/')
        campo = r.context['form'].fields['bodega']
        self.assertEqual(campo.queryset.count(), 2)
        self.assertEqual(campo.empty_label, '— Bodega —')

    def test_presta_y_ajusta_en_cualquier_bodega(self):
        """Fase 3: los caminos sin form de cabecera, también inertes."""
        self._sembrar(self.ajena)
        r = self._post_prestamo(self.ajena)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Prestamo.objects.count(), 1)

        r = self._post_ajuste(self.ajena, 40)
        self.assertEqual(self._stock(self.ajena), 40)
        self.assertTrue(any('ajustado' in m for m in self._mensajes(r)))

    def test_el_select_de_linea_ofrece_todas(self):
        self.assertEqual(
            self.client.get('/prestamos/nuevo/').context['bodegas'].count(), 2)


class SuperusuarioNoRestringidoTest(_BaseDocumentosTest):
    """Tiene fila, pero es superusuario: escribe en la bodega ajena."""

    superusuario = True

    def test_escribe_en_la_bodega_ajena(self):
        r = self._post_entrada(self.ajena)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self._stock(self.ajena), 2)

    def test_traslada_desde_la_ajena(self):
        self._sembrar(self.ajena)
        r = self._post_traslado(self.ajena, self.propia)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self._stock(self.propia), 2)

    def test_presta_y_ajusta_en_la_bodega_ajena(self):
        self._sembrar(self.ajena)
        self.assertEqual(self._post_prestamo(self.ajena).status_code, 302)
        self._post_ajuste(self.ajena, 3)
        self.assertEqual(self._stock(self.ajena), 3)


class AvisoBodegaTest(_BaseDocumentosTest):

    def test_aviso_en_los_formularios(self):
        for url in ('/entradas/nueva/', '/salidas/nueva/', '/traslados/nuevo/',
                    '/devoluciones/nueva/'):
            r = self.client.get(url)
            self.assertContains(r, 'Operas la bodega', msg_prefix=url)
            self.assertContains(r, 'Principal', msg_prefix=url)

    def test_bodega_inactiva_avisa_distinto(self):
        self.propia.activa = False
        self.propia.save(update_fields=['activa'])
        r = self.client.get('/entradas/nueva/')
        self.assertContains(r, 'está')
        self.assertContains(r, 'inactiva')
        # Sin bodega operable el select queda vacío: no puede registrar nada.
        self.assertEqual(r.context['form'].fields['bodega'].queryset.count(), 0)


class SinAvisoBodegaTest(_BaseDocumentosTest):

    asignar = False

    def test_sin_asignacion_no_hay_aviso(self):
        self.assertNotContains(self.client.get('/entradas/nueva/'),
                               'Operas la bodega')


# ---------------------------------------------------------------------------
# Fase 3 — escrituras sin form de cabecera
# ---------------------------------------------------------------------------

class PrestamoRestringidoTest(_BaseDocumentosTest):
    """La bodega va POR LÍNEA: la valida `parsear_lineas_material`."""

    def test_select_de_linea_solo_ofrece_su_bodega(self):
        r = self.client.get('/prestamos/nuevo/')
        self.assertEqual([b.nombre for b in r.context['bodegas']], ['Principal'])

    def test_prestamo_desde_su_bodega(self):
        self._sembrar(self.propia)
        r = self._post_prestamo(self.propia)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Prestamo.objects.count(), 1)
        self.assertEqual(self._stock(self.propia), 8)

    def test_linea_con_bodega_ajena_no_escribe(self):
        self._sembrar(self.ajena)
        r = self._post_prestamo(self.ajena)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Prestamo.objects.count(), 0)
        self.assertEqual(self._stock(self.ajena), 10)
        mensajes = self._mensajes(r)
        self.assertTrue(any('No puedes registrar movimientos' in m
                            for m in mensajes), mensajes)
        # Mensaje DISTINTO del de bodega inexistente/inactiva.
        self.assertFalse(any('sin bodega válida' in m for m in mensajes))

    def test_recibido_tambien_se_restringe(self):
        """RECIBIDO suma stock en esa bodega: es escritura igual que OTORGADO."""
        r = self._post_prestamo(self.ajena,
                                direccion=Prestamo.Direccion.RECIBIDO)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Prestamo.objects.count(), 0)
        self.assertEqual(self._stock(self.ajena), 0)


class DevolucionPrestamoMixtaTest(_BaseDocumentosTest):
    """Préstamo histórico con líneas de dos bodegas: rechazo TOTAL."""

    def setUp(self):
        super().setUp()
        self._sembrar(self.propia)
        self._sembrar(self.ajena)
        # Creado por servicio (como si lo hubiera hecho alguien sin restricción).
        self.prestamo = crear_prestamo(
            tercero=self.tercero, fecha_compromiso=date(2030, 1, 1),
            lineas=[(self.material[3], self.propia, 4),
                    (self.material[3], self.ajena, 5)],
            usuario=self.user)
        self.linea_propia, self.linea_ajena = list(
            self.prestamo.lineas.order_by('bodega__nombre'))
        self.assertEqual(self.linea_propia.bodega, self.propia)

    def _devolver(self, pares):
        return self.client.post(
            f'/prestamos/{self.prestamo.pk}/devolver/',
            {'dev_linea_id': [str(l.pk) for l, _ in pares],
             'dev_cantidad': [str(c) for _, c in pares],
             'observaciones': ''}, follow=True)

    def test_devolver_incluyendo_la_ajena_se_rechaza_entero(self):
        r = self._devolver([(self.linea_propia, 4), (self.linea_ajena, 5)])
        self.assertEqual(Devolucion.objects.count(), 0)
        for linea in (self.linea_propia, self.linea_ajena):
            linea.refresh_from_db()
            self.assertEqual(linea.cantidad_devuelta, 0)
        mensajes = self._mensajes(r)
        self.assertTrue(any('Sucursal' in m and 'Principal' in m
                            for m in mensajes), mensajes)

    def test_devolver_solo_la_propia_pasa_y_deja_parcial(self):
        r = self._devolver([(self.linea_propia, 4)])
        self.assertEqual(Devolucion.objects.count(), 1)
        self.linea_propia.refresh_from_db()
        self.assertEqual(self.linea_propia.cantidad_devuelta, 4)
        self.prestamo.refresh_from_db()
        self.assertEqual(self.prestamo.estado, Prestamo.Estado.PARCIAL)
        self.assertTrue(any('registrada' in m for m in self._mensajes(r)))

    def test_el_modal_bloquea_la_linea_ajena(self):
        r = self.client.get(f'/prestamos/{self.prestamo.pk}/')
        self.assertEqual(r.context['bodegas_operables'], {self.propia.pk})
        self.assertContains(r, 'readonly')


class AjusteRestringidoTest(_BaseDocumentosTest):

    def test_ajuste_en_su_bodega(self):
        self._sembrar(self.propia)
        r = self._post_ajuste(self.propia, 25)
        self.assertEqual(self._stock(self.propia), 25)
        self.assertTrue(any('ajustado' in m for m in self._mensajes(r)))

    def test_ajuste_en_bodega_ajena_no_escribe(self):
        self._sembrar(self.ajena)
        r = self._post_ajuste(self.ajena, 99)
        self.assertEqual(self._stock(self.ajena), 10)
        self.assertEqual(Movimiento.objects.filter(
            tipo__in=(Movimiento.Tipo.AJUSTE_POS,
                      Movimiento.Tipo.AJUSTE_NEG)).count(), 0)
        self.assertTrue(any('No puedes ajustar' in m
                            for m in self._mensajes(r)), self._mensajes(r))

    def test_la_celda_ajena_no_ofrece_ajuste(self):
        self._sembrar(self.ajena)
        r = self.client.get('/stock/')
        self.assertNotContains(r, 'abrirAjuste(this)')
        # Pero la celda sigue enlazando al kardex: la lectura es global.
        self.assertContains(
            r, f'/articulos/{self.material[3].pk}/kardex/?bodega={self.ajena.pk}')

    def test_la_celda_propia_si_ofrece_ajuste(self):
        self._sembrar(self.propia)
        r = self.client.get('/stock/')
        self.assertContains(r, 'abrirAjuste(this)')
        self.assertEqual([f['editable'] for f in r.context['filas']], [True])


@override_settings(MEDIA_ROOT=_MEDIA_TMP, STORAGES=_STORAGE_LOCAL)
class AdjuntoRestringidoTest(_BaseDocumentosTest):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_MEDIA_TMP, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self._sembrar(self.propia)
        self._sembrar(self.ajena)
        self.entrada_propia, self.entrada_ajena = Entrada.objects.order_by('pk')

    def _subir(self, entrada):
        return self.client.post(
            f'/entradas/{entrada.pk}/adjuntos/subir/',
            {'archivo': SimpleUploadedFile('factura.pdf', b'%PDF-1.4 x')},
            follow=True)

    def test_adjunta_a_su_entrada(self):
        self._subir(self.entrada_propia)
        self.assertEqual(AdjuntoEntrada.objects.count(), 1)

    def test_no_adjunta_a_entrada_de_otra_bodega(self):
        r = self._subir(self.entrada_ajena)
        self.assertEqual(AdjuntoEntrada.objects.count(), 0)
        self.assertTrue(any('Sucursal' in m for m in self._mensajes(r)),
                        self._mensajes(r))

    def test_no_elimina_adjunto_de_otra_bodega(self):
        adjunto = AdjuntoEntrada.objects.create(
            entrada=self.entrada_ajena,
            archivo=SimpleUploadedFile('f.pdf', b'%PDF-1.4 x'),
            nombre_original='f.pdf', subido_por=self.user)
        self.client.post(f'/entradas/adjuntos/{adjunto.pk}/eliminar/',
                         follow=True)
        self.assertTrue(AdjuntoEntrada.objects.filter(pk=adjunto.pk).exists())

    def test_descarga_sigue_siendo_global(self):
        adjunto = AdjuntoEntrada.objects.create(
            entrada=self.entrada_ajena,
            archivo=SimpleUploadedFile('f.pdf', b'%PDF-1.4 x'),
            nombre_original='f.pdf', subido_por=self.user)
        r = self.client.get(f'/entradas/adjuntos/{adjunto.pk}/descargar/')
        self.assertEqual(r.status_code, 200)
        r.close()

    def test_el_detalle_ajeno_oculta_la_subida(self):
        propia = self.client.get(f'/entradas/{self.entrada_propia.pk}/')
        self.assertTrue(propia.context['puede_operar'])
        ajena = self.client.get(f'/entradas/{self.entrada_ajena.pk}/')
        self.assertFalse(ajena.context['puede_operar'])
        self.assertNotContains(ajena, 'adjuntos/subir/')


class LecturaGlobalTest(_BaseDocumentosTest):
    """Contra regresiones futuras: NADIE debe scopear los querysets de lectura.

    Un usuario restringido tiene que seguir viendo el movimiento, el stock y los
    documentos de la bodega ajena — es lo que le permite pedir un traslado.
    """

    def setUp(self):
        super().setUp()
        self._sembrar(self.ajena)
        self.entrada_ajena = Entrada.objects.get()
        self.prestamo_ajeno = crear_prestamo(
            tercero=self.tercero, fecha_compromiso=date(2030, 1, 1),
            lineas=[(self.material[3], self.ajena, 2)], usuario=self.user)

    def test_ve_los_datos_de_la_bodega_ajena(self):
        # La lista de préstamos no pinta bodega (es por línea) → va el detalle.
        for url in ('/stock/', '/movimientos/', '/entradas/',
                    f'/entradas/{self.entrada_ajena.pk}/',
                    f'/articulos/{self.material[3].pk}/kardex/'
                    f'?bodega={self.ajena.pk}',
                    f'/prestamos/{self.prestamo_ajeno.pk}/'):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertContains(r, 'Sucursal', msg_prefix=url)

    def test_las_listas_de_documentos_no_se_recortan(self):
        for url in ('/salidas/', '/traslados/', '/prestamos/'):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertEqual(
            self.client.get('/prestamos/').context['prestamos'].count(), 1)

    def test_los_exports_siguen_cubriendo_todas_las_bodegas(self):
        for url in ('/stock/exportar/', '/movimientos/exportar/',
                    '/prestamos/exportar/'):
            r = self.client.post(url, {})
            self.assertEqual(r.status_code, 200, url)
