"""Tests FASE 4: menús granulares en los sidebars.

Cada ítem de `base.html` / `base_financiera.html` / `base_logistica.html` se condiciona
con `request.modulos_permitidos` (slugs con nivel != SIN, que fija el middleware). Sin
overrides el menú es idéntico a hoy; un override SIN oculta el ítem; el acceso cruzado
solo muestra los módulos cruzados. La rama de perfil profesor/colegio queda intacta
(CONTRATO). Se ejercen con `Client(HTTP_HOST='<area>.testserver')` renderizando la landing
del área (núcleo → pasa el gate sin importar los overrides).
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User, Group

from core.areas import (GRUPO_STAFF_FINANCIERA, GRUPO_STAFF_LOGISTICA,
                        GRUPO_STAFF_PROGRAMACION)
from programacion.configuracion.models import Profesor
from usuarios.models import ModuloUsuario, UsuarioProfesor
from usuarios.permisos import COM, SIN


class MenuProgramacionTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.g = Group.objects.get_or_create(name=GRUPO_STAFF_PROGRAMACION)[0]
        self.user = User.objects.create_user('menu_prog', password='x')
        self.user.groups.add(self.g)
        self.client.login(username='menu_prog', password='x')

    def test_staff_sin_overrides_ve_todos_los_modulos(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'href="/auditoria/"')     # módulo auditoria
        self.assertContains(r, 'href="/exportar/"')      # módulo exportar
        self.assertContains(r, 'href="/informes/"')      # módulo informes

    def test_override_sin_auditoria_oculta_el_link(self):
        ModuloUsuario.objects.create(user=self.user, area='programacion',
                                     modulo='auditoria', nivel=SIN)
        r = self.client.get('/')
        self.assertNotContains(r, 'href="/auditoria/"')
        self.assertContains(r, 'href="/informes/"')      # el resto sigue visible


class MenuAccesoCruzadoTest(TestCase):
    """Financiera con un solo override de programación: su sidebar de programación
    muestra únicamente ese módulo (+ núcleo), no el área completa."""

    def setUp(self):
        self.g_fin = Group.objects.get_or_create(name=GRUPO_STAFF_FINANCIERA)[0]
        self.user = User.objects.create_user('cruz_menu', password='x')
        self.user.groups.add(self.g_fin)
        ModuloUsuario.objects.create(user=self.user, area='programacion',
                                     modulo='informes', nivel=COM)

    def test_solo_informes_en_el_sidebar(self):
        c = Client(HTTP_HOST='programacion.testserver')
        c.login(username='cruz_menu', password='x')
        r = c.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'href="/informes/"')
        self.assertNotContains(r, 'href="/auditoria/"')
        self.assertNotContains(r, 'href="/exportar/"')


class MenuFinancieraTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='financiera.testserver')
        self.g = Group.objects.get_or_create(name=GRUPO_STAFF_FINANCIERA)[0]
        self.user = User.objects.create_user('menu_fin', password='x')
        self.user.groups.add(self.g)
        self.client.login(username='menu_fin', password='x')

    def test_staff_ve_proyeccion(self):
        r = self.client.get('/')
        self.assertContains(r, 'href="/pagos/proyeccion/"')

    def test_override_sin_proyeccion_oculta_el_link(self):
        ModuloUsuario.objects.create(user=self.user, area='financiera',
                                     modulo='proyeccion', nivel=SIN)
        r = self.client.get('/')
        self.assertNotContains(r, 'href="/pagos/proyeccion/"')
        self.assertContains(r, 'href="/pagos/"')         # Profesores (pagos) sigue


class MenuLogisticaTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='logistica.testserver')
        self.g = Group.objects.get_or_create(name=GRUPO_STAFF_LOGISTICA)[0]
        self.user = User.objects.create_user('menu_log', password='x')
        self.user.groups.add(self.g)
        self.client.login(username='menu_log', password='x')

    # La landing (log_home) es el dashboard: su CUERPO enlaza a /prestamos/ etc., así que
    # para aislar el SIDEBAR se renderiza /articulos/ (la lista, sin esos links en el body).
    def test_staff_ve_todos_los_modulos(self):
        r = self.client.get('/articulos/')
        self.assertContains(r, 'href="/stock/"')
        self.assertContains(r, 'href="/prestamos/"')

    def test_override_sin_prestamos_oculta_el_link(self):
        ModuloUsuario.objects.create(user=self.user, area='logistica',
                                     modulo='prestamos', nivel=SIN)
        r = self.client.get('/articulos/')
        self.assertNotContains(r, 'href="/prestamos/"')
        self.assertContains(r, 'href="/stock/"')         # el resto sigue visible


class MenuProfesorContratoTest(TestCase):
    """El menú del perfil profesor (else branch, intacto) NO depende de los módulos."""

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.prof = Profesor.objects.create(nombre='Ana', apellido='Pérez')
        self.user = User.objects.create_user('ana_menu', password='x')
        UsuarioProfesor.objects.create(user=self.user, profesor=self.prof)
        self.client.login(username='ana_menu', password='x')

    def test_menu_profesor_tres_items_intacto(self):
        r = self.client.get('/informes/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Cronograma')                    # ver_horario
        self.assertContains(r, 'href="/profesores/pagos/"')     # profesor_pagos
        # No aparecen las secciones de staff.
        self.assertNotContains(r, 'href="/auditoria/"')
        self.assertNotContains(r, 'href="/exportar/"')
