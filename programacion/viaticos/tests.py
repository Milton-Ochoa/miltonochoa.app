"""
Tests — app: viaticos
Modelos: SolicitudViatico, GastoViatico, SoportePago
Vistas (programación): lista/crear/editar/detalle de solicitudes + descarga de soportes.
"""
import shutil
import tempfile
from datetime import date

from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from core.areas import GRUPO_STAFF_PROGRAMACION
from programacion.configuracion.models import Colegio, Profesor
from usuarios.models import UsuarioColegio
from programacion.viaticos.models import GastoViatico, SolicitudViatico, SoportePago

# Almacenamiento local en tmp para los tests de soportes: NUNCA tocar Supabase.
# (default ya es FileSystemStorage en tests; aquí solo se aísla MEDIA_ROOT.)
_STORAGE_LOCAL = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
_MEDIA_TMP_PROG = tempfile.mkdtemp()
_MEDIA_TMP_LEG = tempfile.mkdtemp()


class SolicitudViaticoModelTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('staff', 'staff@x.com', 'x')
        self.profesor = Profesor.objects.create(
            nombre='Juan', apellido='Pérez', documento='123',
            cuenta_bancaria='999-888', banco=Profesor.Banco.BANCOLOMBIA,
        )
        self.colegio = Colegio.objects.create(
            codigo='COL-1', nombre='Colegio Norte',
            departamento='Antioquia', ciudad='Medellín',
        )

    def _crear(self, **kwargs):
        defaults = dict(
            profesor=self.profesor, colegio=self.colegio,
            fecha_viaje=date(2026, 6, 1), fecha_regreso=date(2026, 6, 3),
            creado_por=self.user,
        )
        defaults.update(kwargs)
        s = SolicitudViatico(**defaults)
        s.aplicar_snapshot()
        s.full_clean()
        s.save()
        return s

    def test_aplicar_snapshot_copia_desde_fk(self):
        s = self._crear()
        self.assertEqual(s.docente_nombre, 'Juan Pérez')
        self.assertEqual(s.docente_cedula, '123')
        self.assertEqual(s.docente_cuenta, '999-888')
        self.assertEqual(s.docente_banco, 'Bancolombia')
        self.assertEqual(s.colegio_codigo, 'COL-1')
        self.assertEqual(s.colegio_nombre, 'Colegio Norte')

    def test_snapshot_banco_se_actualiza_al_reaplicar(self):
        """El banco es snapshot: editar reaplica desde la FK (cambia si cambió el maestro)."""
        s = self._crear()
        self.profesor.banco = Profesor.Banco.DAVIVIENDA
        self.profesor.save()
        s.aplicar_snapshot()  # lo que hace la vista al editar
        self.assertEqual(s.docente_banco, 'Davivienda')

    def test_snapshot_banco_vacio_si_profesor_sin_banco(self):
        self.profesor.banco = None
        self.profesor.save()
        s = self._crear()
        self.assertEqual(s.docente_banco, '')

    def test_estado_por_defecto_enviada(self):
        s = self._crear()
        self.assertEqual(s.estado, SolicitudViatico.Estado.ENVIADA)

    def test_total_suma_gastos(self):
        s = self._crear()
        GastoViatico.objects.create(solicitud=s, nombre='Bus', valor=10000, orden=0)
        GastoViatico.objects.create(solicitud=s, nombre='Comida', valor=25000, orden=1)
        self.assertEqual(s.total, 35000)

    def test_total_cero_sin_gastos(self):
        s = self._crear()
        self.assertEqual(s.total, 0)

    def test_fecha_regreso_anterior_a_viaje_invalida(self):
        s = SolicitudViatico(
            profesor=self.profesor, colegio=self.colegio,
            fecha_viaje=date(2026, 6, 3), fecha_regreso=date(2026, 6, 1),
            creado_por=self.user,
        )
        s.aplicar_snapshot()
        with self.assertRaises(ValidationError):
            s.full_clean()

    def test_gastos_ordenados_por_orden(self):
        s = self._crear()
        GastoViatico.objects.create(solicitud=s, nombre='B', valor=2, orden=1)
        GastoViatico.objects.create(solicitud=s, nombre='A', valor=1, orden=0)
        nombres = list(s.gastos.values_list('nombre', flat=True))
        self.assertEqual(nombres, ['A', 'B'])


class ViaticosVistasTest(TestCase):
    """Vistas del área programación. Host de área: programacion.testserver."""

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.admin = User.objects.create_superuser('admin_v', password='pass')
        self.profesor = Profesor.objects.create(
            nombre='Juan', apellido='Pérez', documento='123', cuenta_bancaria='999-888',
        )
        self.colegio = Colegio.objects.create(
            codigo='COL-1', nombre='Colegio Norte', departamento='Antioquia', ciudad='Medellín',
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

    # ── Acceso ──────────────────────────────────────────────
    def test_no_autenticado_redirige(self):
        self.assertEqual(self.client.get('/viaticos/').status_code, 302)

    def test_admin_ve_lista(self):
        self.client.login(username='admin_v', password='pass')
        self.assertEqual(self.client.get('/viaticos/').status_code, 200)

    def test_staff_de_etiqueta_accede(self):
        grupo, _ = Group.objects.get_or_create(name=GRUPO_STAFF_PROGRAMACION)
        staff = User.objects.create_user('staff_v', password='pass')
        staff.groups.add(grupo)
        self.client.login(username='staff_v', password='pass')
        self.assertEqual(self.client.get('/viaticos/').status_code, 200)

    def test_gestor_colegio_sin_acceso(self):
        gestor = User.objects.create_user('gestor_v', password='pass')
        UsuarioColegio.objects.create(user=gestor, colegio=self.colegio)
        self.client.login(username='gestor_v', password='pass')
        self.assertNotEqual(self.client.get('/viaticos/').status_code, 200)

    # ── Crear ───────────────────────────────────────────────
    def test_crear_envia_y_copia_snapshot_desde_fk(self):
        self.client.login(username='admin_v', password='pass')
        r = self.client.post('/viaticos/crear/', {
            'profesor': self.profesor.pk,
            'colegio': self.colegio.pk,
            'fecha_viaje': '2026-06-01',
            'fecha_regreso': '2026-06-03',
            'observaciones': '',
            'gasto_nombre': ['Bus', 'Comida'],
            'gasto_valor': ['10000', '5000'],
            # POST manipulado: el servidor debe IGNORARLO y recalcular desde la FK.
            'docente_nombre': 'HACKEADO',
            'colegio_nombre': 'FALSO',
        })
        self.assertEqual(r.status_code, 302)
        s = SolicitudViatico.objects.get()
        self.assertEqual(s.estado, SolicitudViatico.Estado.ENVIADA)
        self.assertEqual(s.docente_nombre, 'Juan Pérez')
        self.assertEqual(s.docente_cedula, '123')
        self.assertEqual(s.colegio_nombre, 'Colegio Norte')
        self.assertEqual(s.total, 15000)
        self.assertEqual(s.creado_por, self.admin)

    def test_crear_fecha_regreso_anterior_no_crea(self):
        self.client.login(username='admin_v', password='pass')
        r = self.client.post('/viaticos/crear/', {
            'profesor': self.profesor.pk, 'colegio': self.colegio.pk,
            'fecha_viaje': '2026-06-05', 'fecha_regreso': '2026-06-01',
            'gasto_nombre': ['Bus'], 'gasto_valor': ['10000'],
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(SolicitudViatico.objects.count(), 0)

    def test_crear_sin_gastos_no_crea(self):
        self.client.login(username='admin_v', password='pass')
        r = self.client.post('/viaticos/crear/', {
            'profesor': self.profesor.pk, 'colegio': self.colegio.pk,
            'fecha_viaje': '2026-06-01', 'fecha_regreso': '2026-06-03',
            'gasto_nombre': [''], 'gasto_valor': [''],
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(SolicitudViatico.objects.count(), 0)

    def test_crear_gasto_valor_cero_no_crea(self):
        self.client.login(username='admin_v', password='pass')
        r = self.client.post('/viaticos/crear/', {
            'profesor': self.profesor.pk, 'colegio': self.colegio.pk,
            'fecha_viaje': '2026-06-01', 'fecha_regreso': '2026-06-03',
            'gasto_nombre': ['Bus'], 'gasto_valor': ['0'],
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(SolicitudViatico.objects.count(), 0)

    # ── Editar / reenviar ───────────────────────────────────
    def test_editar_devuelta_y_reenviar(self):
        s = self._solicitud(estado=SolicitudViatico.Estado.DEVUELTA,
                            motivo_devolucion='Falta factura')
        self.client.login(username='admin_v', password='pass')
        r = self.client.post(f'/viaticos/{s.pk}/editar/', {
            'profesor': self.profesor.pk, 'colegio': self.colegio.pk,
            'fecha_viaje': '2026-06-01', 'fecha_regreso': '2026-06-04',
            'gasto_nombre': ['Bus', 'Hotel'], 'gasto_valor': ['10000', '20000'],
            'reenviar': '1',
        })
        self.assertEqual(r.status_code, 302)
        s.refresh_from_db()
        self.assertEqual(s.estado, SolicitudViatico.Estado.ENVIADA)
        self.assertEqual(s.motivo_devolucion, '')
        self.assertEqual(s.total, 30000)
        self.assertEqual(s.gastos.count(), 2)

    def test_editar_guardar_sin_reenviar_mantiene_estado(self):
        s = self._solicitud(estado=SolicitudViatico.Estado.DEVUELTA,
                            motivo_devolucion='Falta factura')
        self.client.login(username='admin_v', password='pass')
        r = self.client.post(f'/viaticos/{s.pk}/editar/', {
            'profesor': self.profesor.pk, 'colegio': self.colegio.pk,
            'fecha_viaje': '2026-06-01', 'fecha_regreso': '2026-06-03',
            'gasto_nombre': ['Bus'], 'gasto_valor': ['12000'],
        })
        self.assertEqual(r.status_code, 302)
        s.refresh_from_db()
        self.assertEqual(s.estado, SolicitudViatico.Estado.DEVUELTA)
        self.assertEqual(s.motivo_devolucion, 'Falta factura')

    def test_editar_aprobada_bloqueada(self):
        s = self._solicitud(estado=SolicitudViatico.Estado.APROBADA)
        self.client.login(username='admin_v', password='pass')
        r = self.client.get(f'/viaticos/{s.pk}/editar/')
        self.assertEqual(r.status_code, 302)  # redirige al detalle (no editable)

    def test_detalle_muestra_motivo_devolucion(self):
        s = self._solicitud(estado=SolicitudViatico.Estado.DEVUELTA,
                            motivo_devolucion='Falta factura')
        self.client.login(username='admin_v', password='pass')
        r = self.client.get(f'/viaticos/{s.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Falta factura')


@override_settings(VIATICOS_NOTIFICAR_A='financiera@aamo.test')
class ViaticosNotificacionEmailTest(TestCase):
    """Al pasar a ENVIADA (crear o reenviar) se avisa por correo a financiera.

    El envío va en transaction.on_commit → se envuelve con captureOnCommitCallbacks
    para que los callbacks corran dentro del TestCase (que usa transacción)."""

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.admin = User.objects.create_superuser('admin_n', password='pass')
        self.client.login(username='admin_n', password='pass')
        self.profesor = Profesor.objects.create(
            nombre='Juan', apellido='Pérez', documento='123', cuenta_bancaria='999-888',
        )
        self.colegio = Colegio.objects.create(
            codigo='COL-1', nombre='Colegio Norte', departamento='Antioquia', ciudad='Medellín',
        )

    def _solicitud(self, estado, **kwargs):
        s = SolicitudViatico(
            profesor=self.profesor, colegio=self.colegio,
            fecha_viaje=date(2026, 6, 1), fecha_regreso=date(2026, 6, 3),
            estado=estado, creado_por=self.admin, **kwargs,
        )
        s.aplicar_snapshot()
        s.save()
        GastoViatico.objects.create(solicitud=s, nombre='Bus', valor=10000, orden=0)
        return s

    def test_crear_envia_correo_a_financiera(self):
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post('/viaticos/crear/', {
                'profesor': self.profesor.pk, 'colegio': self.colegio.pk,
                'fecha_viaje': '2026-06-01', 'fecha_regreso': '2026-06-03',
                'gasto_nombre': ['Bus'], 'gasto_valor': ['10000'],
            })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, ['financiera@aamo.test'])
        s = SolicitudViatico.objects.get()
        self.assertIn(f'#{s.pk}', m.subject)
        self.assertIn('Juan Pérez', m.body)

    def test_reenviar_devuelta_envia_correo(self):
        s = self._solicitud(SolicitudViatico.Estado.DEVUELTA, motivo_devolucion='Falta factura')
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(f'/viaticos/{s.pk}/editar/', {
                'profesor': self.profesor.pk, 'colegio': self.colegio.pk,
                'fecha_viaje': '2026-06-01', 'fecha_regreso': '2026-06-03',
                'gasto_nombre': ['Bus'], 'gasto_valor': ['10000'],
                'reenviar': '1',
            })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)

    def test_editar_sin_reenviar_no_envia_correo(self):
        s = self._solicitud(SolicitudViatico.Estado.DEVUELTA, motivo_devolucion='Falta factura')
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(f'/viaticos/{s.pk}/editar/', {
                'profesor': self.profesor.pk, 'colegio': self.colegio.pk,
                'fecha_viaje': '2026-06-01', 'fecha_regreso': '2026-06-03',
                'gasto_nombre': ['Bus'], 'gasto_valor': ['12000'],
            })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)


@override_settings(MEDIA_ROOT=_MEDIA_TMP_PROG, STORAGES=_STORAGE_LOCAL)
class SoporteDescargaProgramacionTest(TestCase):
    """Programación ve/descarga (solo lectura) el soporte de pago subido por financiera.
    El archivo se sirve por una vista protegida (proxy), con el nombre limpio del upload_to."""

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.admin = User.objects.create_superuser('admin_s', password='pass')
        self.profesor = Profesor.objects.create(
            nombre='Juan', apellido='Pérez', documento='123', cuenta_bancaria='999-888',
        )
        self.colegio = Colegio.objects.create(
            codigo='COL-1', nombre='Colegio Norte', departamento='Antioquia', ciudad='Medellín',
        )
        self.solicitud = SolicitudViatico(
            profesor=self.profesor, colegio=self.colegio,
            fecha_viaje=date(2026, 6, 1), fecha_regreso=date(2026, 6, 3),
            estado=SolicitudViatico.Estado.PAGADA, creado_por=self.admin,
        )
        self.solicitud.aplicar_snapshot()
        self.solicitud.save()
        self.soporte = SoportePago.objects.create(
            solicitud=self.solicitud,
            archivo=SimpleUploadedFile('comprobante.pdf', b'%PDF-1.4 datos', content_type='application/pdf'),
            nombre_original='comprobante.pdf', subido_por=self.admin,
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_MEDIA_TMP_PROG, ignore_errors=True)
        super().tearDownClass()

    def test_descarga_attachment_con_nombre_limpio(self):
        self.client.login(username='admin_s', password='pass')
        r = self.client.get(f'/viaticos/soporte/{self.soporte.pk}/')
        self.assertEqual(r.status_code, 200)
        disp = r['Content-Disposition']
        self.assertIn('attachment', disp)
        # El nombre de descarga es el limpio del upload_to: viatico-<slug>-<fecha>.pdf
        self.assertIn('viatico-juan-perez-2026-06-01.pdf', disp)

    def test_ver_inline(self):
        self.client.login(username='admin_s', password='pass')
        r = self.client.get(f'/viaticos/soporte/{self.soporte.pk}/?inline=1')
        self.assertEqual(r.status_code, 200)
        self.assertIn('inline', r['Content-Disposition'])

    def test_sin_permiso_redirige(self):
        """Un gestor de colegio (sin acceso al área completa) no descarga el soporte."""
        gestor = User.objects.create_user('gestor_s', password='pass')
        UsuarioColegio.objects.create(user=gestor, colegio=self.colegio)
        self.client.login(username='gestor_s', password='pass')
        r = self.client.get(f'/viaticos/soporte/{self.soporte.pk}/')
        self.assertEqual(r.status_code, 302)


@override_settings(MEDIA_ROOT=_MEDIA_TMP_LEG, STORAGES=_STORAGE_LOCAL,
                   VIATICOS_LEGALIZACION_NOTIFICAR_A='financiero@aamo.test')
class LegalizacionProgramacionTest(TestCase):
    """Legalización post-pago: programación adjunta soportes (tipo LEGALIZACION) en
    PAGADA/LEG_DEVUELTA y los envía a financiera (LEG_ENVIADA + correo)."""

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.admin = User.objects.create_superuser('admin_l', password='pass')
        self.client.login(username='admin_l', password='pass')
        self.profesor = Profesor.objects.create(
            nombre='Juan', apellido='Pérez', documento='123', cuenta_bancaria='999-888',
        )
        self.colegio = Colegio.objects.create(
            codigo='COL-1', nombre='Colegio Norte', departamento='Antioquia', ciudad='Medellín',
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_MEDIA_TMP_LEG, ignore_errors=True)
        super().tearDownClass()

    def _solicitud(self, estado=SolicitudViatico.Estado.PAGADA, **kwargs):
        s = SolicitudViatico(
            profesor=self.profesor, colegio=self.colegio,
            fecha_viaje=date(2026, 6, 1), fecha_regreso=date(2026, 6, 3),
            estado=estado, creado_por=self.admin, **kwargs,
        )
        s.aplicar_snapshot()
        s.save()
        return s

    def _pdf(self, nombre='legalizacion.pdf'):
        return SimpleUploadedFile(nombre, b'%PDF-1.4 datos', content_type='application/pdf')

    def _soporte_leg(self, s):
        return SoportePago.objects.create(
            solicitud=s, tipo=SoportePago.Tipo.LEGALIZACION,
            archivo=self._pdf(), nombre_original='legalizacion.pdf', subido_por=self.admin,
        )

    # ── Subir ───────────────────────────────────────────────
    def test_subir_en_pagada_crea_soporte_legalizacion(self):
        s = self._solicitud()
        r = self.client.post(f'/viaticos/{s.pk}/legalizacion/soporte/', {'archivo': self._pdf()})
        self.assertEqual(r.status_code, 302)
        soporte = s.soportes.get()
        self.assertEqual(soporte.tipo, SoportePago.Tipo.LEGALIZACION)
        self.assertEqual(soporte.subido_por, self.admin)

    def test_subir_en_leg_devuelta_permitido(self):
        s = self._solicitud(SolicitudViatico.Estado.LEG_DEVUELTA, motivo_devolucion='Falta recibo')
        self.client.post(f'/viaticos/{s.pk}/legalizacion/soporte/', {'archivo': self._pdf()})
        self.assertEqual(s.soportes.count(), 1)

    def test_subir_en_aprobada_rechazado(self):
        s = self._solicitud(SolicitudViatico.Estado.APROBADA)
        self.client.post(f'/viaticos/{s.pk}/legalizacion/soporte/', {'archivo': self._pdf()})
        self.assertEqual(s.soportes.count(), 0)

    def test_subir_en_leg_enviada_rechazado(self):
        """Tras enviar, los soportes quedan congelados hasta que financiera devuelva."""
        s = self._solicitud(SolicitudViatico.Estado.LEG_ENVIADA)
        self.client.post(f'/viaticos/{s.pk}/legalizacion/soporte/', {'archivo': self._pdf()})
        self.assertEqual(s.soportes.count(), 0)

    # ── Eliminar ────────────────────────────────────────────
    def test_eliminar_soporte_legalizacion_en_pagada(self):
        s = self._solicitud()
        soporte = self._soporte_leg(s)
        r = self.client.post(f'/viaticos/legalizacion/soporte/{soporte.pk}/eliminar/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(s.soportes.count(), 0)

    def test_eliminar_soporte_tipo_pago_da_404(self):
        """Programación no puede borrar soportes de pago (son de financiera)."""
        s = self._solicitud()
        soporte_pago = SoportePago.objects.create(
            solicitud=s, archivo=self._pdf('pago.pdf'), nombre_original='pago.pdf',
        )
        r = self.client.post(f'/viaticos/legalizacion/soporte/{soporte_pago.pk}/eliminar/')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(s.soportes.count(), 1)

    def test_eliminar_en_leg_enviada_bloqueado(self):
        s = self._solicitud(SolicitudViatico.Estado.LEG_ENVIADA)
        soporte = self._soporte_leg(s)
        self.client.post(f'/viaticos/legalizacion/soporte/{soporte.pk}/eliminar/')
        self.assertEqual(s.soportes.count(), 1)

    # ── Enviar ──────────────────────────────────────────────
    def test_enviar_sin_soporte_rechazado(self):
        s = self._solicitud()
        self.client.post(f'/viaticos/{s.pk}/legalizacion/enviar/')
        s.refresh_from_db()
        self.assertEqual(s.estado, SolicitudViatico.Estado.PAGADA)

    def test_enviar_con_soporte_pasa_a_leg_enviada_y_notifica(self):
        s = self._solicitud()
        self._soporte_leg(s)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(f'/viaticos/{s.pk}/legalizacion/enviar/')
        self.assertEqual(r.status_code, 302)
        s.refresh_from_db()
        self.assertEqual(s.estado, SolicitudViatico.Estado.LEG_ENVIADA)
        self.assertIsNotNone(s.legalizacion_enviada_en)
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, ['financiero@aamo.test'])
        self.assertIn('Legalización', m.subject)

    def test_reenviar_desde_leg_devuelta_limpia_motivo(self):
        s = self._solicitud(SolicitudViatico.Estado.LEG_DEVUELTA, motivo_devolucion='Falta recibo')
        self._soporte_leg(s)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f'/viaticos/{s.pk}/legalizacion/enviar/')
        s.refresh_from_db()
        self.assertEqual(s.estado, SolicitudViatico.Estado.LEG_ENVIADA)
        self.assertEqual(s.motivo_devolucion, '')

    def test_enviar_desde_aprobada_rechazado(self):
        s = self._solicitud(SolicitudViatico.Estado.APROBADA)
        self._soporte_leg(s)
        self.client.post(f'/viaticos/{s.pk}/legalizacion/enviar/')
        s.refresh_from_db()
        self.assertEqual(s.estado, SolicitudViatico.Estado.APROBADA)

    def test_soporte_pago_no_cuenta_para_enviar(self):
        """El requisito de ≥1 soporte es de LEGALIZACIÓN: uno de pago no habilita el envío."""
        s = self._solicitud()
        SoportePago.objects.create(solicitud=s, archivo=self._pdf('pago.pdf'))
        self.client.post(f'/viaticos/{s.pk}/legalizacion/enviar/')
        s.refresh_from_db()
        self.assertEqual(s.estado, SolicitudViatico.Estado.PAGADA)
