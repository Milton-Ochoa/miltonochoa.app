"""Tests del área financiera — pagos de **monitores** (simulacros).

Financiera **solo gestiona filas de lotes ENVIADO** por programación: marca el pago
(fija `fecha_pago`/`marcado_por`), lo desmarca (limpia esos campos y borra soportes, sin
borrar la fila) y sube/elimina soportes. La materialización semanal la cubren los tests
de programación; aquí se valida la gestión propia y el gate de área. Espejo de
``financiera.pagos.tests``.
"""
import shutil
import tempfile
from datetime import date

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User, Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from core.areas import GRUPO_STAFF_FINANCIERA, GRUPO_STAFF_PROGRAMACION
from programacion.monitores.models import (
    ColegioSimulacro, LoteMonitores, Monitor, PagoMonitor,
    SoportePagoMonitor, Simulacro)

# Soportes en disco local aislado en tmp: NUNCA tocar Supabase (igual que viáticos).
_STORAGE_LOCAL = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
_MEDIA_TMP = tempfile.mkdtemp()


def _crear_pago(monitor, simulacro, *, estado=LoteMonitores.Estado.ENVIADO,
                fecha=date(2025, 3, 15)):
    """Crea un lote en el estado dado con una fila base lista para financiera."""
    lote = LoteMonitores.objects.create(
        fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 3, 16), estado=estado)
    return PagoMonitor.objects.create(
        lote=lote, monitor=monitor, simulacro=simulacro,
        fecha=fecha, valor=simulacro.valor)


class FinMonitoresPagosTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='financiera.testserver')
        self.grupo_fin = Group.objects.get(name=GRUPO_STAFF_FINANCIERA)
        self.grupo_prog = Group.objects.get(name=GRUPO_STAFF_PROGRAMACION)

        colegio = ColegioSimulacro.objects.create(
            nombre='Colegio Simulacro Norte', ciudad='Bucaramanga', departamento='Santander')
        self.simulacro = Simulacro.objects.create(
            colegio=colegio, fecha=date(2025, 3, 15), valor=90000)
        self.monitor = Monitor.objects.create(nombre='Ana', apellido='Pérez')

        self.finan = User.objects.create_user(username='finan', password='pass')
        self.finan.groups.add(self.grupo_fin)

    def _login_financiera(self):
        self.client.login(username='finan', password='pass')

    # ── Acceso ────────────────────────────────────────────────
    def test_lista_200_para_financiera(self):
        self._login_financiera()
        r = self.client.get('/monitores/pagos/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'tablaPagos')

    def test_lista_rechaza_usuario_solo_programacion(self):
        u = User.objects.create_user(username='prog', password='pass')
        u.groups.add(self.grupo_prog)
        self.client.login(username='prog', password='pass')
        r = self.client.get('/monitores/pagos/')
        self.assertNotEqual(r.status_code, 200)  # middleware lo saca del subdominio

    def test_lista_solo_muestra_lotes_enviados(self):
        self._login_financiera()
        _crear_pago(self.monitor, self.simulacro, estado=LoteMonitores.Estado.BORRADOR)
        r = self.client.get('/monitores/pagos/?semana=2025-03-10&tab=pendiente')
        self.assertNotContains(r, 'Pérez')

    # ── Marcar / desmarcar ────────────────────────────────────
    def test_marcar_fija_fecha_pago(self):
        self._login_financiera()
        pago = _crear_pago(self.monitor, self.simulacro)
        r = self.client.post('/monitores/pagos/marcar/', {'accion': 'marcar', 'pago_id': pago.id})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])
        pago.refresh_from_db()
        self.assertIsNotNone(pago.fecha_pago)
        self.assertEqual(pago.marcado_por, self.finan)

    def test_marcar_es_idempotente(self):
        self._login_financiera()
        pago = _crear_pago(self.monitor, self.simulacro)
        self.client.post('/monitores/pagos/marcar/', {'accion': 'marcar', 'pago_id': pago.id})
        self.client.post('/monitores/pagos/marcar/', {'accion': 'marcar', 'pago_id': pago.id})
        self.assertEqual(PagoMonitor.objects.count(), 1)  # no duplica filas

    def test_marcar_rechaza_lote_no_enviado(self):
        self._login_financiera()
        pago = _crear_pago(self.monitor, self.simulacro, estado=LoteMonitores.Estado.BORRADOR)
        r = self.client.post('/monitores/pagos/marcar/', {'accion': 'marcar', 'pago_id': pago.id})
        self.assertEqual(r.status_code, 400)
        pago.refresh_from_db()
        self.assertIsNone(pago.fecha_pago)

    def test_desmarcar_limpia_pero_conserva_fila(self):
        self._login_financiera()
        pago = _crear_pago(self.monitor, self.simulacro)
        pago.fecha_pago = timezone.now()
        pago.marcado_por = self.finan
        pago.save()
        r = self.client.post('/monitores/pagos/marcar/', {'accion': 'desmarcar', 'pago_id': pago.id})
        self.assertTrue(r.json()['ok'])
        pago.refresh_from_db()
        self.assertIsNone(pago.fecha_pago)
        self.assertEqual(PagoMonitor.objects.count(), 1)

    def test_marcar_requiere_financiera(self):
        pago = _crear_pago(self.monitor, self.simulacro)
        r = self.client.post('/monitores/pagos/marcar/', {'accion': 'marcar', 'pago_id': pago.id})
        self.assertNotEqual(r.status_code, 200)
        pago.refresh_from_db()
        self.assertIsNone(pago.fecha_pago)

    # ── Exportar ──────────────────────────────────────────────
    def test_exportar_devuelve_xlsx(self):
        self._login_financiera()
        r = self.client.post('/monitores/pagos/exportar/', {
            'fecha_inicio': '2025-03-10', 'fecha_fin': '2025-03-16', 'tab': 'pendiente',
        })
        self.assertEqual(r.status_code, 200)
        self.assertIn('spreadsheetml', r['Content-Type'])
        self.assertIn('attachment', r['Content-Disposition'])

    # ── Detalle ───────────────────────────────────────────────
    def test_detalle_muestra_datos_y_desglose(self):
        self._login_financiera()
        pago = _crear_pago(self.monitor, self.simulacro)
        from programacion.monitores.models import ExtraPagoMonitor
        ExtraPagoMonitor.objects.create(pago=pago, concepto='Refrigerio', valor=15000)
        r = self.client.get(f'/monitores/pagos/{pago.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Colegio Simulacro Norte')
        self.assertContains(r, 'Refrigerio')  # el desglose
        self.assertContains(r, 'Soporte de pago')

    # ── Menú ──────────────────────────────────────────────────
    def test_menu_enlaza_monitores(self):
        self._login_financiera()
        r = self.client.get('/monitores/pagos/')
        self.assertContains(r, '/monitores/pagos/')


@override_settings(MEDIA_ROOT=_MEDIA_TMP, STORAGES=_STORAGE_LOCAL)
class FinMonitoresSoporteTest(TestCase):
    """Subida/eliminación/descarga de soportes en disco local aislado."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_MEDIA_TMP, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.client = Client(HTTP_HOST='financiera.testserver')
        grupo_fin = Group.objects.get(name=GRUPO_STAFF_FINANCIERA)
        self.finan = User.objects.create_user(username='finan', password='pass')
        self.finan.groups.add(grupo_fin)
        self.client.login(username='finan', password='pass')

        colegio = ColegioSimulacro.objects.create(
            nombre='Colegio Simulacro Norte', ciudad='Bucaramanga', departamento='Santander')
        simulacro = Simulacro.objects.create(
            colegio=colegio, fecha=date(2025, 3, 15), valor=90000)
        monitor = Monitor.objects.create(nombre='Ana', apellido='Pérez')
        self.pago = _crear_pago(monitor, simulacro)

    def _archivo(self, nombre='comprobante.pdf', contenido=b'%PDF-1.4 fake'):
        return SimpleUploadedFile(nombre, contenido, content_type='application/pdf')

    def test_subir_soporte_ok(self):
        r = self.client.post(f'/monitores/pagos/{self.pago.pk}/soporte/', {'archivo': self._archivo()})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.pago.soportes.count(), 1)
        soporte = self.pago.soportes.first()
        self.assertEqual(soporte.subido_por, self.finan)
        self.assertTrue(soporte.archivo.name.startswith('pagos-monitores/pago-ana-perez-2025-03-15'))

    def test_subir_extension_invalida_rechazada(self):
        r = self.client.post(f'/monitores/pagos/{self.pago.pk}/soporte/',
                             {'archivo': self._archivo('virus.exe', b'MZ')})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.pago.soportes.count(), 0)

    def test_eliminar_soporte(self):
        self.client.post(f'/monitores/pagos/{self.pago.pk}/soporte/', {'archivo': self._archivo()})
        soporte = self.pago.soportes.first()
        r = self.client.post(f'/monitores/pagos/soporte/{soporte.pk}/eliminar/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.pago.soportes.count(), 0)

    def test_descargar_soporte(self):
        self.client.post(f'/monitores/pagos/{self.pago.pk}/soporte/', {'archivo': self._archivo()})
        soporte = self.pago.soportes.first()
        r = self.client.get(f'/monitores/pagos/soporte/{soporte.pk}/descargar/')
        self.assertEqual(r.status_code, 200)

    def test_desmarcar_borra_soporte_pero_conserva_fila(self):
        self.pago.fecha_pago = timezone.now()
        self.pago.save()
        self.client.post(f'/monitores/pagos/{self.pago.pk}/soporte/', {'archivo': self._archivo()})
        self.assertEqual(SoportePagoMonitor.objects.count(), 1)
        self.client.post('/monitores/pagos/marcar/', {'accion': 'desmarcar', 'pago_id': self.pago.id})
        self.pago.refresh_from_db()
        self.assertIsNone(self.pago.fecha_pago)
        self.assertEqual(PagoMonitor.objects.count(), 1)
        self.assertEqual(SoportePagoMonitor.objects.count(), 0)


@override_settings(MEDIA_ROOT=_MEDIA_TMP, STORAGES=_STORAGE_LOCAL)
class FinMonitoresLoteNoEnviadoTest(TestCase):
    """Regresión: financiera solo ve lo enviado. Detalle, soportes y descarga deben
    rechazar filas cuyo lote no esté ENVIADO (mismo guard que fin_monitores_pagos_marcar)."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_MEDIA_TMP, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.client = Client(HTTP_HOST='financiera.testserver')
        grupo_fin = Group.objects.get(name=GRUPO_STAFF_FINANCIERA)
        self.finan = User.objects.create_user(username='finan', password='pass')
        self.finan.groups.add(grupo_fin)
        self.client.login(username='finan', password='pass')

        colegio = ColegioSimulacro.objects.create(
            nombre='Colegio Simulacro Norte', ciudad='Bucaramanga', departamento='Santander')
        simulacro = Simulacro.objects.create(
            colegio=colegio, fecha=date(2025, 3, 15), valor=90000)
        monitor = Monitor.objects.create(nombre='Ana', apellido='Pérez')
        self.pago = _crear_pago(monitor, simulacro, estado=LoteMonitores.Estado.BORRADOR)

    def _archivo(self):
        return SimpleUploadedFile('comprobante.pdf', b'%PDF-1.4 fake',
                                  content_type='application/pdf')

    def _soporte_borrador(self):
        return SoportePagoMonitor.objects.create(
            pago=self.pago, archivo=self._archivo(),
            nombre_original='comprobante.pdf', subido_por=self.finan)

    def test_detalle_rechaza_lote_borrador(self):
        r = self.client.get(f'/monitores/pagos/{self.pago.pk}/')
        self.assertEqual(r.status_code, 302)  # redirect a la lista, no muestra la fila

    def test_subir_soporte_rechaza_lote_borrador(self):
        r = self.client.post(f'/monitores/pagos/{self.pago.pk}/soporte/', {'archivo': self._archivo()})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.pago.soportes.count(), 0)

    def test_eliminar_soporte_rechaza_lote_borrador(self):
        soporte = self._soporte_borrador()
        r = self.client.post(f'/monitores/pagos/soporte/{soporte.pk}/eliminar/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.pago.soportes.count(), 1)  # sigue existiendo

    def test_descargar_soporte_rechaza_lote_borrador(self):
        soporte = self._soporte_borrador()
        r = self.client.get(f'/monitores/pagos/soporte/{soporte.pk}/descargar/')
        self.assertEqual(r.status_code, 404)


class FinMonitoresBadgeTest(TestCase):
    """El badge financiera cuenta filas ENVIADO no pagadas (no excluidas)."""

    def setUp(self):
        self.client = Client(HTTP_HOST='financiera.testserver')
        grupo_fin = Group.objects.get(name=GRUPO_STAFF_FINANCIERA)
        self.finan = User.objects.create_user(username='finan', password='pass')
        self.finan.groups.add(grupo_fin)
        self.client.login(username='finan', password='pass')

        colegio = ColegioSimulacro.objects.create(
            nombre='Colegio Simulacro Norte', ciudad='Bucaramanga', departamento='Santander')
        self.simulacro = Simulacro.objects.create(
            colegio=colegio, fecha=date(2025, 3, 15), valor=90000)
        self.monitor = Monitor.objects.create(nombre='Ana', apellido='Pérez')

    def test_badge_cuenta_enviadas_no_pagadas(self):
        _crear_pago(self.monitor, self.simulacro)  # ENVIADO, no pagada → cuenta
        r = self.client.get('/monitores/pagos/')
        self.assertEqual(r.context['pagos_monitores_pendientes_count'], 1)
