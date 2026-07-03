"""Tests de permisos granulares por módulo.

FASE 2 (inerte): resolución (`usuarios/permisos.py`), catálogo (`core/modulos.py`) y
sanidad. FASE 3: enforcement en el middleware + acceso cruzado (predicados de
`core.areas`), ejercido con `Client(HTTP_HOST='<area>.testserver')`.
"""
import json

from django.test import TestCase, Client
from django.contrib.auth.models import User, Group

from core.areas import (AREAS, GRUPO_STAFF_FINANCIERA, GRUPO_STAFF_LOGISTICA,
                        GRUPO_STAFF_PROGRAMACION, areas_del_usuario,
                        es_personal_financiera, es_personal_programacion)
from core import modulos as cat
from usuarios.models import ModuloUsuario, PerfilEmpleado
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


# ── Enforcement en el middleware (FASE 3) ─────────────────────────
# Se ejerce contra el área financiera (la más simple: sin perfiles colegio/profesor).

class EnforcementFinancieraTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='financiera.testserver')
        self.g_fin = Group.objects.get_or_create(name=GRUPO_STAFF_FINANCIERA)[0]
        self.user = User.objects.create_user('fin_mw', password='x')
        self.user.groups.add(self.g_fin)
        self.client.login(username='fin_mw', password='x')

    def test_retro_grupo_sin_overrides_accede(self):
        # Sin overrides, el grupo se comporta igual que hoy: acceso pleno al módulo.
        self.assertEqual(self.client.get('/viaticos/').status_code, 200)

    def test_sin_acceso_redirige_a_landing(self):
        ModuloUsuario.objects.create(user=self.user, area='financiera',
                                     modulo='viaticos', nivel=SIN)
        r = self.client.get('/viaticos/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], '/')          # landing (fin_home), bucle-safe

    def test_lectura_get_ok_post_bloqueado_html(self):
        ModuloUsuario.objects.create(user=self.user, area='financiera',
                                     modulo='viaticos', nivel=LEC)
        self.assertEqual(self.client.get('/viaticos/').status_code, 200)
        # POST de escritura (navegación normal, sin Sec-Fetch-Mode) → página 403 HTML.
        r = self.client.post('/viaticos/1/aprobar/')
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, 'solo lectura', status_code=403)

    def test_lectura_post_ajax_devuelve_json_403(self):
        ModuloUsuario.objects.create(user=self.user, area='financiera',
                                     modulo='viaticos', nivel=LEC)
        r = self.client.post('/viaticos/1/aprobar/', HTTP_SEC_FETCH_MODE='cors')
        self.assertEqual(r.status_code, 403)
        self.assertFalse(r.json()['ok'])
        self.assertIn('solo lectura', r.json()['error'])

    def test_lectura_permite_export_post(self):
        # El export (POST de lectura) sí pasa en modo LECTURA (posts_lectura, exacto).
        ModuloUsuario.objects.create(user=self.user, area='financiera',
                                     modulo='viaticos', nivel=LEC)
        r = self.client.post('/viaticos/exportar/', {'estados': ['APROBADA']})
        self.assertNotEqual(r.status_code, 403)

    def test_cambio_password_precede_al_gate(self):
        # Un empleado con clave pendiente va a cambiar-password ANTES de cualquier gate.
        PerfilEmpleado.objects.create(user=self.user, debe_cambiar_password=True)
        ModuloUsuario.objects.create(user=self.user, area='financiera',
                                     modulo='viaticos', nivel=SIN)
        r = self.client.get('/viaticos/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('cambiar-password', r['Location'])


class AccesoCruzadoTest(TestCase):
    """Usuario de financiera con un override de programación: entra a programación
    solo por su módulo cruzado; el resto del área queda bloqueado."""

    def setUp(self):
        self.g_fin = Group.objects.get_or_create(name=GRUPO_STAFF_FINANCIERA)[0]
        self.user = User.objects.create_user('cruzado_mw', password='x')
        self.user.groups.add(self.g_fin)
        ModuloUsuario.objects.create(user=self.user, area='programacion',
                                     modulo='informes', nivel=COM)

    def test_entra_a_su_modulo_cruzado(self):
        c = Client(HTTP_HOST='programacion.testserver')
        c.login(username='cruzado_mw', password='x')
        self.assertEqual(c.get('/informes/').status_code, 200)

    def test_bloqueado_en_modulo_no_cruzado(self):
        c = Client(HTTP_HOST='programacion.testserver')
        c.login(username='cruzado_mw', password='x')
        r = c.get('/colegios/')                       # colegios sigue SIN → landing
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], '/')

    def test_areas_del_usuario_ofrece_ambas(self):
        slugs = {a['slug'] for a in areas_del_usuario(self.user)}
        self.assertEqual(slugs, {'financiera', 'programacion'})

    def test_predicados_reconocen_el_override(self):
        # Los ~112 decoradores de vista dejan pasar al usuario cruzado.
        self.assertTrue(es_personal_programacion(self.user))
        self.assertTrue(es_personal_financiera(self.user))


# ── UI de permisos en el panel del apex (FASE 5) ──────────────────
# Endpoints AJAX GET/POST bajo /usuarios/ajax/area/permisos/. Se ejercen desde el apex
# (host por defecto testserver), donde el superusuario administra los usuarios de etiqueta.

class PanelPermisosAjaxTest(TestCase):

    def setUp(self):
        self.client = Client()  # apex
        self.admin = User.objects.create_superuser('admin_perm', 'a@x.com', 'x')
        self.client.login(username='admin_perm', password='x')
        self.g_fin = Group.objects.get_or_create(name=GRUPO_STAFF_FINANCIERA)[0]
        self.empleado = User.objects.create_user('emp_fin', password='x')
        self.empleado.groups.add(self.g_fin)

    def test_get_estructura_y_defaults(self):
        r = self.client.get('/usuarios/ajax/area/permisos/', {'user_id': self.empleado.id})
        data = r.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['username'], 'emp_fin')
        areas = {a['slug']: a for a in data['areas']}
        self.assertEqual(set(areas), {'programacion', 'financiera', 'logistica'})
        # De su grupo (financiera): default COMPLETO en todos los módulos.
        fin = areas['financiera']
        self.assertTrue(fin['de_su_grupo'])
        self.assertTrue(all(m['nivel_default'] == COM for m in fin['modulos']))
        self.assertTrue(all(m['nivel'] == COM and not m['es_override'] for m in fin['modulos']))
        # Fuera de su grupo (programacion): default SIN_ACCESO.
        prog = areas['programacion']
        self.assertFalse(prog['de_su_grupo'])
        self.assertTrue(all(m['nivel_default'] == SIN for m in prog['modulos']))

    def test_get_refleja_override_existente(self):
        ModuloUsuario.objects.create(user=self.empleado, area='financiera',
                                     modulo='viaticos', nivel=LEC)
        r = self.client.get('/usuarios/ajax/area/permisos/', {'user_id': self.empleado.id})
        fin = next(a for a in r.json()['areas'] if a['slug'] == 'financiera')
        viaticos = next(m for m in fin['modulos'] if m['slug'] == 'viaticos')
        self.assertEqual(viaticos['nivel'], LEC)
        self.assertTrue(viaticos['es_override'])

    def test_get_usuario_superusuario_400(self):
        r = self.client.get('/usuarios/ajax/area/permisos/', {'user_id': self.admin.id})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()['ok'])

    def test_post_crea_override(self):
        permisos = [{'area': 'financiera', 'modulo': 'viaticos', 'nivel': LEC}]
        r = self.client.post('/usuarios/ajax/area/permisos/guardar/',
                             {'user_id': self.empleado.id, 'permisos': json.dumps(permisos)})
        self.assertTrue(r.json()['ok'])
        ov = ModuloUsuario.objects.get(user=self.empleado, area='financiera', modulo='viaticos')
        self.assertEqual(ov.nivel, LEC)
        self.assertEqual(ov.actualizado_por, self.admin)

    def test_post_nivel_por_defecto_borra_override(self):
        # Regla sparse: guardar el nivel por defecto (COM para su grupo) borra la fila.
        ModuloUsuario.objects.create(user=self.empleado, area='financiera',
                                     modulo='viaticos', nivel=SIN)
        permisos = [{'area': 'financiera', 'modulo': 'viaticos', 'nivel': COM}]
        r = self.client.post('/usuarios/ajax/area/permisos/guardar/',
                             {'user_id': self.empleado.id, 'permisos': json.dumps(permisos)})
        self.assertTrue(r.json()['ok'])
        self.assertFalse(ModuloUsuario.objects.filter(
            user=self.empleado, area='financiera', modulo='viaticos').exists())

    def test_post_cruzado_com_fuera_del_grupo_persiste(self):
        # COMPLETO en un área ajena (default SIN) NO es el default → se persiste (acceso cruzado).
        permisos = [{'area': 'programacion', 'modulo': 'informes', 'nivel': COM}]
        self.client.post('/usuarios/ajax/area/permisos/guardar/',
                         {'user_id': self.empleado.id, 'permisos': json.dumps(permisos)})
        self.assertTrue(ModuloUsuario.objects.filter(
            user=self.empleado, area='programacion', modulo='informes', nivel=COM).exists())

    def test_post_modulo_invalido_400_sin_escribir(self):
        permisos = [{'area': 'financiera', 'modulo': 'no_existe', 'nivel': LEC}]
        r = self.client.post('/usuarios/ajax/area/permisos/guardar/',
                             {'user_id': self.empleado.id, 'permisos': json.dumps(permisos)})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(ModuloUsuario.objects.filter(user=self.empleado).exists())

    def test_post_nivel_invalido_400(self):
        permisos = [{'area': 'financiera', 'modulo': 'viaticos', 'nivel': 'XXX'}]
        r = self.client.post('/usuarios/ajax/area/permisos/guardar/',
                             {'user_id': self.empleado.id, 'permisos': json.dumps(permisos)})
        self.assertEqual(r.status_code, 400)

    def test_post_permisos_no_json_400(self):
        r = self.client.post('/usuarios/ajax/area/permisos/guardar/',
                             {'user_id': self.empleado.id, 'permisos': 'no-es-json'})
        self.assertEqual(r.status_code, 400)

    def test_post_usuario_superusuario_400(self):
        permisos = [{'area': 'financiera', 'modulo': 'viaticos', 'nivel': LEC}]
        r = self.client.post('/usuarios/ajax/area/permisos/guardar/',
                             {'user_id': self.admin.id, 'permisos': json.dumps(permisos)})
        self.assertEqual(r.status_code, 400)

    def test_no_superusuario_redirige(self):
        c = Client()
        c.login(username='emp_fin', password='x')  # etiqueta, no admin
        r = c.get('/usuarios/ajax/area/permisos/', {'user_id': self.empleado.id})
        self.assertEqual(r.status_code, 302)
        self.assertIn('/usuarios/login/', r['Location'])

    def test_integracion_lec_por_endpoint_bloquea_en_middleware(self):
        # Guardar LEC en viáticos por el panel y verificar que el middleware bloquea el POST.
        permisos = [{'area': 'financiera', 'modulo': 'viaticos', 'nivel': LEC}]
        self.client.post('/usuarios/ajax/area/permisos/guardar/',
                         {'user_id': self.empleado.id, 'permisos': json.dumps(permisos)})
        area_client = Client(HTTP_HOST='financiera.testserver')
        area_client.login(username='emp_fin', password='x')
        self.assertEqual(area_client.get('/viaticos/').status_code, 200)      # lectura OK
        r = area_client.post('/viaticos/1/aprobar/', HTTP_SEC_FETCH_MODE='cors')
        self.assertEqual(r.status_code, 403)                                   # escritura bloqueada
