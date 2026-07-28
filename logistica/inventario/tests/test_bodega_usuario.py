"""Tests de la restricción de escritura por bodega — Fase 1: el modelo
`BodegaUsuario`, los helpers de `permisos.py` y la página de asignación.

En esta fase NADA cambia todavía en las vistas de escritura (eso llega en las
fases siguientes); lo que se blinda aquí es la semántica del helper —sobre todo
los dos casos que mantienen verde el resto de la suite: **sin fila = sin
restricción** y **superusuario nunca restringido**— y el gate de la página.

Mismo arnés que el resto del área: `Client(HTTP_HOST='logistica.testserver')`.
"""
from django.contrib.auth.models import AnonymousUser, Group, User
from django.db.models import ProtectedError
from django.test import Client, TestCase

from core.areas import GRUPO_STAFF_FINANCIERA, GRUPO_STAFF_LOGISTICA

from logistica.inventario.models import Bodega, BodegaUsuario
from logistica.inventario.permisos import (BodegaNoPermitida, bodega_asignada,
                                           bodegas_escribibles, es_restringido,
                                           exigir_bodega, exigir_bodegas,
                                           puede_escribir_en)


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
