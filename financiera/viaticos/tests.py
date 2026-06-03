"""Tests del área financiera.

Fase 3: enrutado por subdominio, gating de acceso (superusuario / grupo
`area:financiera` / otros) y que el área programación sigue intacta tras el
refactor del chrome.

Fase 4: gestión de viáticos (listar/devolver/aprobar/pagar/editar), el badge de
pendientes y el flujo cruzado programación ↔ financiera.
"""
from datetime import date

from django.test import TestCase, Client
from django.contrib.auth.models import User, Group

from core.areas import GRUPO_STAFF_FINANCIERA, GRUPO_STAFF_PROGRAMACION
from programacion.configuracion.models import Colegio, Profesor
from programacion.viaticos.models import GastoViatico, SolicitudViatico


class FinancieraAccesoTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='financiera.testserver')
        # Los grupos los crean las migraciones 0004/0006; en tests existen ya.
        self.grupo_fin = Group.objects.get(name=GRUPO_STAFF_FINANCIERA)
        self.grupo_prog = Group.objects.get(name=GRUPO_STAFF_PROGRAMACION)

    def test_anonimo_redirige_a_login_apex(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/usuarios/login/', r['Location'])

    def test_superusuario_ve_inicio(self):
        User.objects.create_superuser(username='admin', password='pass')
        self.client.login(username='admin', password='pass')
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Financiera AAMO')

    def test_staff_financiera_ve_inicio(self):
        u = User.objects.create_user(username='finan', password='pass')
        u.groups.add(self.grupo_fin)
        self.client.login(username='finan', password='pass')
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Financiera AAMO')

    def test_staff_financiera_ve_viaticos_placeholder(self):
        u = User.objects.create_user(username='finan2', password='pass')
        u.groups.add(self.grupo_fin)
        self.client.login(username='finan2', password='pass')
        r = self.client.get('/viaticos/')
        self.assertEqual(r.status_code, 200)

    def test_usuario_solo_programacion_es_redirigido(self):
        """Un usuario sin acceso a financiera va al selector de área del apex,
        no se le hace logout (puede tener otra área)."""
        u = User.objects.create_user(username='prog', password='pass')
        u.groups.add(self.grupo_prog)
        self.client.login(username='prog', password='pass')
        r = self.client.get('/')
        self.assertEqual(r.status_code, 302)
        # Redirige al apex (host sin el subdominio financiera).
        self.assertNotIn('financiera.testserver', r['Location'])


class SubdominioDesconocidoTest(TestCase):

    def test_subdominio_no_registrado_da_404(self):
        c = Client(HTTP_HOST='logistica.testserver')
        r = c.get('/')
        self.assertEqual(r.status_code, 404)


class ProgramacionIntactaTest(TestCase):
    """Tras el refactor del chrome (base_chrome.html), el área programación
    sigue cargando con su sidebar."""

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')

    def test_home_programacion_superusuario_ok(self):
        User.objects.create_superuser(username='admin', password='pass')
        self.client.login(username='admin', password='pass')
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Programación AAMO')


class FinancieraGestionViaticosTest(TestCase):
    """Gestión de viáticos por financiera (Fase 4): devolver / aprobar / pagar /
    editar, badge de pendientes y aislamiento entre áreas."""

    def setUp(self):
        self.client = Client(HTTP_HOST='financiera.testserver')
        self.admin = User.objects.create_superuser('fin_admin', password='pass')
        self.profesor = Profesor.objects.create(
            nombre='Ana', apellido='Gómez', documento='555', cuenta_bancaria='111-222',
        )
        self.colegio = Colegio.objects.create(
            codigo='C-9', nombre='Colegio Sur', departamento='Valle', ciudad='Cali',
        )

    def _solicitud(self, estado=SolicitudViatico.Estado.ENVIADA, **kwargs):
        s = SolicitudViatico(
            profesor=self.profesor, colegio=self.colegio,
            fecha_viaje=date(2026, 6, 1), fecha_regreso=date(2026, 6, 3),
            estado=estado, creado_por=self.admin, **kwargs,
        )
        s.aplicar_snapshot()
        s.save()
        GastoViatico.objects.create(solicitud=s, nombre='Bus', valor=10000, orden=0)
        return s

    def _login_financiera(self):
        self.client.login(username='fin_admin', password='pass')

    # ── Lista / badge ───────────────────────────────────────
    def test_lista_muestra_solicitud(self):
        self._solicitud()
        self._login_financiera()
        r = self.client.get('/viaticos/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Ana Gómez')

    def test_badge_cuenta_solo_enviadas(self):
        self._solicitud(estado=SolicitudViatico.Estado.ENVIADA)
        self._solicitud(estado=SolicitudViatico.Estado.APROBADA)
        self._login_financiera()
        r = self.client.get('/')
        self.assertEqual(r.context['viaticos_pendientes_count'], 1)

    # ── Devolver ────────────────────────────────────────────
    def test_devolver_con_motivo(self):
        s = self._solicitud()
        self._login_financiera()
        r = self.client.post(f'/viaticos/{s.pk}/devolver/', {'motivo_devolucion': 'Falta factura'})
        self.assertEqual(r.status_code, 302)
        s.refresh_from_db()
        self.assertEqual(s.estado, SolicitudViatico.Estado.DEVUELTA)
        self.assertEqual(s.motivo_devolucion, 'Falta factura')
        self.assertIsNotNone(s.devuelto_en)
        self.assertEqual(s.gestionado_por, self.admin)

    def test_devolver_sin_motivo_no_cambia(self):
        s = self._solicitud()
        self._login_financiera()
        self.client.post(f'/viaticos/{s.pk}/devolver/', {'motivo_devolucion': '   '})
        s.refresh_from_db()
        self.assertEqual(s.estado, SolicitudViatico.Estado.ENVIADA)

    def test_devolver_no_enviada_bloqueada(self):
        s = self._solicitud(estado=SolicitudViatico.Estado.APROBADA)
        self._login_financiera()
        self.client.post(f'/viaticos/{s.pk}/devolver/', {'motivo_devolucion': 'X'})
        s.refresh_from_db()
        self.assertEqual(s.estado, SolicitudViatico.Estado.APROBADA)

    # ── Aprobar / pagar ─────────────────────────────────────
    def test_aprobar_enviada(self):
        s = self._solicitud()
        self._login_financiera()
        self.client.post(f'/viaticos/{s.pk}/aprobar/')
        s.refresh_from_db()
        self.assertEqual(s.estado, SolicitudViatico.Estado.APROBADA)
        self.assertIsNotNone(s.aprobado_en)

    def test_aprobar_no_enviada_bloqueada(self):
        s = self._solicitud(estado=SolicitudViatico.Estado.APROBADA)
        self._login_financiera()
        self.client.post(f'/viaticos/{s.pk}/aprobar/')
        s.refresh_from_db()
        self.assertIsNone(s.aprobado_en)

    def test_pagar_aprobada(self):
        s = self._solicitud(estado=SolicitudViatico.Estado.APROBADA)
        self._login_financiera()
        self.client.post(f'/viaticos/{s.pk}/pagar/')
        s.refresh_from_db()
        self.assertEqual(s.estado, SolicitudViatico.Estado.PAGADA)
        self.assertIsNotNone(s.pagado_en)

    def test_pagar_no_aprobada_bloqueada(self):
        s = self._solicitud(estado=SolicitudViatico.Estado.ENVIADA)
        self._login_financiera()
        self.client.post(f'/viaticos/{s.pk}/pagar/')
        s.refresh_from_db()
        self.assertEqual(s.estado, SolicitudViatico.Estado.ENVIADA)

    def test_get_no_dispara_accion(self):
        """Las acciones son POST-only (require_POST): un GET no cambia el estado."""
        s = self._solicitud()
        self._login_financiera()
        r = self.client.get(f'/viaticos/{s.pk}/aprobar/')
        self.assertEqual(r.status_code, 405)
        s.refresh_from_db()
        self.assertEqual(s.estado, SolicitudViatico.Estado.ENVIADA)

    # ── Editar ──────────────────────────────────────────────
    def test_editar_aprobada_reemplaza_gastos(self):
        s = self._solicitud(estado=SolicitudViatico.Estado.APROBADA)
        self._login_financiera()
        r = self.client.post(f'/viaticos/{s.pk}/editar/', {
            'profesor': self.profesor.pk, 'colegio': self.colegio.pk,
            'fecha_viaje': '2026-06-01', 'fecha_regreso': '2026-06-05',
            'gasto_nombre': ['Bus', 'Hotel'], 'gasto_valor': ['10000', '40000'],
        })
        self.assertEqual(r.status_code, 302)
        s.refresh_from_db()
        self.assertEqual(s.estado, SolicitudViatico.Estado.APROBADA)  # editar no cambia estado
        self.assertEqual(s.total, 50000)
        self.assertEqual(s.gastos.count(), 2)

    def test_editar_pagada_bloqueada(self):
        s = self._solicitud(estado=SolicitudViatico.Estado.PAGADA)
        self._login_financiera()
        r = self.client.get(f'/viaticos/{s.pk}/editar/')
        self.assertEqual(r.status_code, 302)  # terminal → redirige al detalle

    def test_editar_devuelta_bloqueada(self):
        """Una DEVUELTA pertenece a programación; financiera no la edita."""
        s = self._solicitud(estado=SolicitudViatico.Estado.DEVUELTA, motivo_devolucion='X')
        self._login_financiera()
        r = self.client.get(f'/viaticos/{s.pk}/editar/')
        self.assertEqual(r.status_code, 302)

    # ── Aislamiento entre áreas ─────────────────────────────
    def test_usuario_solo_programacion_no_gestiona_financiera(self):
        s = self._solicitud()
        grupo_prog, _ = Group.objects.get_or_create(name=GRUPO_STAFF_PROGRAMACION)
        u = User.objects.create_user('solo_prog', password='pass')
        u.groups.add(grupo_prog)
        self.client.login(username='solo_prog', password='pass')
        r = self.client.post(f'/viaticos/{s.pk}/aprobar/')
        # El middleware lo manda al selector de área del apex (no gestiona).
        self.assertEqual(r.status_code, 302)
        self.assertNotIn('financiera.testserver', r['Location'])
        s.refresh_from_db()
        self.assertEqual(s.estado, SolicitudViatico.Estado.ENVIADA)


class FlujoViaticosCruzadoTest(TestCase):
    """Flujo end-to-end cruzando programación ↔ financiera con el mismo dato (BD única)."""

    def setUp(self):
        self.prog = Client(HTTP_HOST='programacion.testserver')
        self.fin = Client(HTTP_HOST='financiera.testserver')
        self.admin = User.objects.create_superuser('jefe', password='pass')
        self.profesor = Profesor.objects.create(
            nombre='Leo', apellido='Díaz', documento='777', cuenta_bancaria='333-444',
        )
        self.colegio = Colegio.objects.create(
            codigo='C-3', nombre='Colegio Centro', departamento='Cundinamarca', ciudad='Bogotá',
        )

    def test_enviar_devolver_reenviar_aprobar_pagar(self):
        self.prog.login(username='jefe', password='pass')
        self.fin.login(username='jefe', password='pass')

        # 1) Programación crea/envía
        self.prog.post('/viaticos/crear/', {
            'profesor': self.profesor.pk, 'colegio': self.colegio.pk,
            'fecha_viaje': '2026-06-01', 'fecha_regreso': '2026-06-03',
            'gasto_nombre': ['Bus'], 'gasto_valor': ['10000'],
        })
        s = SolicitudViatico.objects.get()
        self.assertEqual(s.estado, SolicitudViatico.Estado.ENVIADA)

        # 2) Financiera devuelve con motivo
        self.fin.post(f'/viaticos/{s.pk}/devolver/', {'motivo_devolucion': 'Falta hotel'})
        s.refresh_from_db()
        self.assertEqual(s.estado, SolicitudViatico.Estado.DEVUELTA)

        # 3) Programación ve el motivo y reenvía
        r = self.prog.get(f'/viaticos/{s.pk}/')
        self.assertContains(r, 'Falta hotel')
        self.prog.post(f'/viaticos/{s.pk}/editar/', {
            'profesor': self.profesor.pk, 'colegio': self.colegio.pk,
            'fecha_viaje': '2026-06-01', 'fecha_regreso': '2026-06-04',
            'gasto_nombre': ['Bus', 'Hotel'], 'gasto_valor': ['10000', '50000'],
            'reenviar': '1',
        })
        s.refresh_from_db()
        self.assertEqual(s.estado, SolicitudViatico.Estado.ENVIADA)
        self.assertEqual(s.motivo_devolucion, '')
        self.assertEqual(s.total, 60000)

        # 4) Financiera aprueba y paga
        self.fin.post(f'/viaticos/{s.pk}/aprobar/')
        s.refresh_from_db()
        self.assertEqual(s.estado, SolicitudViatico.Estado.APROBADA)
        self.fin.post(f'/viaticos/{s.pk}/pagar/')
        s.refresh_from_db()
        self.assertEqual(s.estado, SolicitudViatico.Estado.PAGADA)

        # 5) Terminal: programación ya no puede editar
        r = self.prog.get(f'/viaticos/{s.pk}/editar/')
        self.assertEqual(r.status_code, 302)
