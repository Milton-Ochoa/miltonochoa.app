"""Tests de la FASE 2 de permisos granulares por módulo (inerte).

Cubren la resolución (`usuarios/permisos.py`), el catálogo (`core/modulos.py`) y su
sanidad. NO tocan runtime todavía (el enforcement es FASE 3).
"""
from django.test import TestCase
from django.contrib.auth.models import User, Group

from core.areas import (AREAS, GRUPO_STAFF_FINANCIERA, GRUPO_STAFF_LOGISTICA,
                        GRUPO_STAFF_PROGRAMACION)
from core import modulos as cat
from usuarios.models import ModuloUsuario
from usuarios.permisos import COM, LEC, SIN, resolver_acceso_area, tiene_overrides_en


# ── Resolución (usuarios/permisos.py) ─────────────────────────────

class ResolverAccesoAreaTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.g_prog = Group.objects.get_or_create(name=GRUPO_STAFF_PROGRAMACION)[0]
        cls.g_fin  = Group.objects.get_or_create(name=GRUPO_STAFF_FINANCIERA)[0]

    def test_grupo_sin_overrides_todo_completo(self):
        u = User.objects.create_user('staff_prog', password='x')
        u.groups.add(self.g_prog)
        acceso, modulos = resolver_acceso_area(u, 'programacion')
        self.assertTrue(acceso)
        self.assertEqual(set(modulos), set(cat.slugs_de_area('programacion')))
        self.assertTrue(all(n == COM for n in modulos.values()))

    def test_sin_grupo_todo_sin_acceso(self):
        u = User.objects.create_user('nadie', password='x')
        acceso, modulos = resolver_acceso_area(u, 'programacion')
        self.assertFalse(acceso)
        self.assertTrue(all(n == SIN for n in modulos.values()))

    def test_superusuario_todo_completo(self):
        u = User.objects.create_superuser('root', 'root@x.com', 'x')
        acceso, modulos = resolver_acceso_area(u, 'logistica')
        self.assertTrue(acceso)
        self.assertTrue(all(n == COM for n in modulos.values()))

    def test_grupo_con_override_lectura(self):
        u = User.objects.create_user('staff_lec', password='x')
        u.groups.add(self.g_prog)
        ModuloUsuario.objects.create(user=u, area='programacion', modulo='auditoria', nivel=LEC)
        acceso, modulos = resolver_acceso_area(u, 'programacion')
        self.assertTrue(acceso)
        self.assertEqual(modulos['auditoria'], LEC)
        self.assertEqual(modulos['colegios'], COM)  # el resto sin override sigue COM

    def test_override_sin_excluye_modulo(self):
        u = User.objects.create_user('staff_sin', password='x')
        u.groups.add(self.g_prog)
        ModuloUsuario.objects.create(user=u, area='programacion', modulo='pagos', nivel=SIN)
        _, modulos = resolver_acceso_area(u, 'programacion')
        self.assertEqual(modulos['pagos'], SIN)
        self.assertEqual(modulos['colegios'], COM)

    def test_acceso_cruzado_sin_grupo_con_un_override_completo(self):
        # Usuario de financiera con un módulo de programación → entra a programación.
        u = User.objects.create_user('cruzado', password='x')
        u.groups.add(self.g_fin)
        ModuloUsuario.objects.create(user=u, area='programacion', modulo='informes', nivel=COM)
        acceso, modulos = resolver_acceso_area(u, 'programacion')
        self.assertTrue(acceso)
        self.assertEqual(modulos['informes'], COM)
        self.assertEqual(modulos['colegios'], SIN)  # los demás siguen sin acceso

    def test_override_a_slug_obsoleto_se_ignora(self):
        u = User.objects.create_user('obsoleto', password='x')
        u.groups.add(self.g_prog)
        ModuloUsuario.objects.create(user=u, area='programacion', modulo='no_existe', nivel=SIN)
        acceso, modulos = resolver_acceso_area(u, 'programacion')
        self.assertTrue(acceso)
        self.assertNotIn('no_existe', modulos)


class TieneOverridesEnTest(TestCase):

    def test_solo_override_con_acceso_cuenta(self):
        u = User.objects.create_user('ov', password='x')
        ModuloUsuario.objects.create(user=u, area='logistica', modulo='stock', nivel=SIN)
        self.assertFalse(tiene_overrides_en(u, 'logistica'))
        ModuloUsuario.objects.create(user=u, area='logistica', modulo='articulos', nivel=LEC)
        self.assertTrue(tiene_overrides_en(u, 'logistica'))

    def test_sin_filas_es_false(self):
        u = User.objects.create_user('limpio', password='x')
        self.assertFalse(tiene_overrides_en(u, 'financiera'))


# ── Catálogo (core/modulos.py) ────────────────────────────────────

class ModuloDePathTest(TestCase):

    def test_longest_prefix_proyeccion_gana_a_pagos(self):
        self.assertEqual(cat.modulo_de_path('financiera', '/pagos/proyeccion/').slug, 'proyeccion')
        self.assertEqual(cat.modulo_de_path('financiera', '/pagos/proyeccion/exportar/').slug,
                         'proyeccion')
        self.assertEqual(cat.modulo_de_path('financiera', '/pagos/').slug, 'pagos')
        self.assertEqual(cat.modulo_de_path('financiera', '/pagos/123/').slug, 'pagos')

    def test_path_no_catalogado_es_none(self):
        self.assertIsNone(cat.modulo_de_path('programacion', '/pendientes/'))
        self.assertIsNone(cat.modulo_de_path('programacion', '/'))
        self.assertIsNone(cat.modulo_de_path('logistica', '/loquesea/'))

    def test_es_raiz(self):
        self.assertTrue(cat.es_raiz('/'))
        self.assertFalse(cat.es_raiz('/pagos/'))

    def test_modulo_por_slug(self):
        self.assertEqual(cat.modulo_por_slug('logistica', 'stock').nombre, 'Existencias')
        self.assertIsNone(cat.modulo_por_slug('logistica', 'inexistente'))


class CatalogoSanidadTest(TestCase):

    def test_areas_del_catalogo_son_subset_de_AREAS(self):
        self.assertTrue(set(cat.MODULOS) <= set(AREAS))
        self.assertTrue(set(cat.NUCLEO) <= set(AREAS))

    def test_slugs_unicos_por_area(self):
        for area, mods in cat.MODULOS.items():
            slugs = [m.slug for m in mods]
            self.assertEqual(len(slugs), len(set(slugs)), f'slugs duplicados en {area}')

    def test_posts_lectura_dentro_del_modulo(self):
        # Cada POST de lectura debe estar bajo un prefijo del módulo y resolver a ese
        # mismo módulo por longest-prefix (evita que un export "de lectura" caiga en otro).
        for area, mods in cat.MODULOS.items():
            for mod in mods:
                for p in mod.posts_lectura:
                    self.assertTrue(any(p.startswith(pre) for pre in mod.prefijos),
                                    f'{area}/{mod.slug}: {p} fuera de sus prefijos')
                    self.assertEqual(cat.modulo_de_path(area, p).slug, mod.slug,
                                     f'{area}/{mod.slug}: {p} resuelve a otro módulo')

    def test_niveles_de_permisos_en_sync_con_el_modelo(self):
        self.assertEqual((SIN, LEC, COM),
                         (ModuloUsuario.Nivel.SIN_ACCESO,
                          ModuloUsuario.Nivel.LECTURA,
                          ModuloUsuario.Nivel.COMPLETO))
