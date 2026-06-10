"""Tests del área financiera — pagos de clases a profesores.

Financiera **solo gestiona filas de lotes ENVIADO** por programación: marca el pago
(fija `fecha_pago`/`marcado_por`), lo desmarca (limpia esos campos y borra soportes, sin
borrar la fila) y sube/elimina soportes. El cálculo semanal y la materialización los
cubren los tests de programación; aquí se valida la gestión propia y el gate de área.
"""
import shutil
import tempfile
from datetime import date

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User, Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from core.areas import GRUPO_STAFF_FINANCIERA, GRUPO_STAFF_PROGRAMACION
from programacion.configuracion.models import Colegio, ColegioAnio, Profesor
from programacion.pagos.models import LotePagos, PagoRealizado, SoportePagoProfesor

# Soportes en disco local aislado en tmp: NUNCA tocar Supabase (igual que viáticos).
_STORAGE_LOCAL = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
_MEDIA_TMP_PAGOS = tempfile.mkdtemp()


def _crear_pago(colegio_anio, profesor, *, estado=LotePagos.Estado.ENVIADO, fecha=date(2025, 3, 14)):
    """Crea un lote en el estado dado con una fila base lista para financiera."""
    lote = LotePagos.objects.create(
        fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 3, 14), estado=estado)
    return PagoRealizado.objects.create(
        lote=lote, profesor=profesor, colegio=colegio_anio,
        fecha=fecha, horas=2, valor=80000)


class FinPagosTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='financiera.testserver')
        self.grupo_fin = Group.objects.get(name=GRUPO_STAFF_FINANCIERA)
        self.grupo_prog = Group.objects.get(name=GRUPO_STAFF_PROGRAMACION)

        colegio = Colegio.objects.create(
            nombre='Colegio Central', departamento='Santander', ciudad='Bucaramanga')
        self.colegio_anio = ColegioAnio.objects.create(colegio=colegio, anio=2025)
        self.profesor = Profesor.objects.create(nombre='Ana', apellido='Pérez')

        self.finan = User.objects.create_user(username='finan', password='pass')
        self.finan.groups.add(self.grupo_fin)

    def _login_financiera(self):
        self.client.login(username='finan', password='pass')

    # ── Acceso ────────────────────────────────────────────────
    def test_lista_200_para_financiera(self):
        self._login_financiera()
        r = self.client.get('/pagos/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'tablaPagos')

    def test_lista_rechaza_usuario_solo_programacion(self):
        u = User.objects.create_user(username='prog', password='pass')
        u.groups.add(self.grupo_prog)
        self.client.login(username='prog', password='pass')
        r = self.client.get('/pagos/')
        self.assertNotEqual(r.status_code, 200)  # middleware lo saca del subdominio

    def test_lista_solo_muestra_lotes_enviados(self):
        self._login_financiera()
        # Lote en BORRADOR → financiera no lo ve.
        _crear_pago(self.colegio_anio, self.profesor, estado=LotePagos.Estado.BORRADOR)
        r = self.client.get('/pagos/?semana=2025-03-10&tab=pendiente')
        self.assertNotContains(r, 'Pérez')

    # ── Marcar / desmarcar ────────────────────────────────────
    def test_marcar_fija_fecha_pago(self):
        self._login_financiera()
        pago = _crear_pago(self.colegio_anio, self.profesor)
        r = self.client.post('/pagos/marcar/', {'accion': 'marcar', 'pago_id': pago.id})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])
        pago.refresh_from_db()
        self.assertIsNotNone(pago.fecha_pago)
        self.assertEqual(pago.marcado_por, self.finan)

    def test_marcar_es_idempotente(self):
        self._login_financiera()
        pago = _crear_pago(self.colegio_anio, self.profesor)
        self.client.post('/pagos/marcar/', {'accion': 'marcar', 'pago_id': pago.id})
        self.client.post('/pagos/marcar/', {'accion': 'marcar', 'pago_id': pago.id})
        self.assertEqual(PagoRealizado.objects.count(), 1)  # no duplica filas

    def test_marcar_rechaza_lote_no_enviado(self):
        self._login_financiera()
        pago = _crear_pago(self.colegio_anio, self.profesor, estado=LotePagos.Estado.BORRADOR)
        r = self.client.post('/pagos/marcar/', {'accion': 'marcar', 'pago_id': pago.id})
        self.assertEqual(r.status_code, 400)
        pago.refresh_from_db()
        self.assertIsNone(pago.fecha_pago)

    def test_desmarcar_limpia_pero_conserva_fila(self):
        self._login_financiera()
        pago = _crear_pago(self.colegio_anio, self.profesor)
        pago.fecha_pago = timezone.now()
        pago.marcado_por = self.finan
        pago.save()
        r = self.client.post('/pagos/marcar/', {'accion': 'desmarcar', 'pago_id': pago.id})
        self.assertTrue(r.json()['ok'])
        pago.refresh_from_db()
        self.assertIsNone(pago.fecha_pago)               # ya no pagada
        self.assertEqual(PagoRealizado.objects.count(), 1)  # la fila sigue

    def test_marcar_requiere_financiera(self):
        # Sin login → no debe marcar (redirige a login/apex).
        pago = _crear_pago(self.colegio_anio, self.profesor)
        r = self.client.post('/pagos/marcar/', {'accion': 'marcar', 'pago_id': pago.id})
        self.assertNotEqual(r.status_code, 200)
        pago.refresh_from_db()
        self.assertIsNone(pago.fecha_pago)

    # ── Exportar ──────────────────────────────────────────────
    def test_exportar_devuelve_xlsx(self):
        self._login_financiera()
        r = self.client.post('/pagos/exportar/', {
            'fecha_inicio': '2025-03-10', 'fecha_fin': '2025-03-14', 'tab': 'pendiente',
        })
        self.assertEqual(r.status_code, 200)
        self.assertIn('spreadsheetml', r['Content-Type'])
        self.assertIn('attachment', r['Content-Disposition'])

    # ── Detalle ───────────────────────────────────────────────
    def test_detalle_muestra_datos_y_desglose(self):
        self._login_financiera()
        pago = _crear_pago(self.colegio_anio, self.profesor)
        from programacion.pagos.models import ExtraPago
        ExtraPago.objects.create(pago=pago, concepto='Desplazamiento', valor=15000)
        r = self.client.get(f'/pagos/{pago.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Colegio Central')
        self.assertContains(r, 'Desplazamiento')  # el desglose
        self.assertContains(r, 'Soporte de pago')


@override_settings(MEDIA_ROOT=_MEDIA_TMP_PAGOS, STORAGES=_STORAGE_LOCAL)
class FinPagosSoporteTest(TestCase):
    """Subida/eliminación/descarga de soportes en disco local aislado."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_MEDIA_TMP_PAGOS, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.client = Client(HTTP_HOST='financiera.testserver')
        grupo_fin = Group.objects.get(name=GRUPO_STAFF_FINANCIERA)
        self.finan = User.objects.create_user(username='finan', password='pass')
        self.finan.groups.add(grupo_fin)
        self.client.login(username='finan', password='pass')

        colegio = Colegio.objects.create(
            nombre='Colegio Central', departamento='Santander', ciudad='Bucaramanga')
        colegio_anio = ColegioAnio.objects.create(colegio=colegio, anio=2025)
        profesor = Profesor.objects.create(nombre='Ana', apellido='Pérez')
        self.pago = _crear_pago(colegio_anio, profesor)

    def _archivo(self, nombre='comprobante.pdf', contenido=b'%PDF-1.4 fake'):
        return SimpleUploadedFile(nombre, contenido, content_type='application/pdf')

    def test_subir_soporte_ok(self):
        r = self.client.post(f'/pagos/{self.pago.pk}/soporte/', {'archivo': self._archivo()})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.pago.soportes.count(), 1)
        soporte = self.pago.soportes.first()
        self.assertEqual(soporte.subido_por, self.finan)
        self.assertTrue(soporte.archivo.name.startswith('pagos/pago-ana-perez-2025-03-14'))

    def test_subir_extension_invalida_rechazada(self):
        r = self.client.post(f'/pagos/{self.pago.pk}/soporte/',
                             {'archivo': self._archivo('virus.exe', b'MZ')})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.pago.soportes.count(), 0)

    def test_eliminar_soporte(self):
        self.client.post(f'/pagos/{self.pago.pk}/soporte/', {'archivo': self._archivo()})
        soporte = self.pago.soportes.first()
        r = self.client.post(f'/pagos/soporte/{soporte.pk}/eliminar/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.pago.soportes.count(), 0)

    def test_descargar_soporte(self):
        self.client.post(f'/pagos/{self.pago.pk}/soporte/', {'archivo': self._archivo()})
        soporte = self.pago.soportes.first()
        r = self.client.get(f'/pagos/soporte/{soporte.pk}/descargar/')
        self.assertEqual(r.status_code, 200)

    def test_desmarcar_borra_soporte_pero_conserva_fila(self):
        # Subir un soporte y luego desmarcar: el archivo y el soporte se van; la fila queda.
        self.pago.fecha_pago = timezone.now()
        self.pago.save()
        self.client.post(f'/pagos/{self.pago.pk}/soporte/', {'archivo': self._archivo()})
        self.assertEqual(SoportePagoProfesor.objects.count(), 1)
        self.client.post('/pagos/marcar/', {'accion': 'desmarcar', 'pago_id': self.pago.id})
        self.pago.refresh_from_db()
        self.assertIsNone(self.pago.fecha_pago)
        self.assertEqual(PagoRealizado.objects.count(), 1)
        self.assertEqual(SoportePagoProfesor.objects.count(), 0)


@override_settings(MEDIA_ROOT=_MEDIA_TMP_PAGOS, STORAGES=_STORAGE_LOCAL)
class FinPagosLoteNoEnviadoTest(TestCase):
    """Regresión: financiera solo ve lo enviado. Detalle, soportes y descarga deben
    rechazar filas cuyo lote no esté ENVIADO (mismo guard que fin_pagos_marcar)."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_MEDIA_TMP_PAGOS, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.client = Client(HTTP_HOST='financiera.testserver')
        grupo_fin = Group.objects.get(name=GRUPO_STAFF_FINANCIERA)
        self.finan = User.objects.create_user(username='finan', password='pass')
        self.finan.groups.add(grupo_fin)
        self.client.login(username='finan', password='pass')

        colegio = Colegio.objects.create(
            nombre='Colegio Central', departamento='Santander', ciudad='Bucaramanga')
        colegio_anio = ColegioAnio.objects.create(colegio=colegio, anio=2025)
        profesor = Profesor.objects.create(nombre='Ana', apellido='Pérez')
        self.pago = _crear_pago(colegio_anio, profesor, estado=LotePagos.Estado.BORRADOR)

    def _archivo(self):
        return SimpleUploadedFile('comprobante.pdf', b'%PDF-1.4 fake',
                                  content_type='application/pdf')

    def _soporte_borrador(self):
        return SoportePagoProfesor.objects.create(
            pago=self.pago, archivo=self._archivo(),
            nombre_original='comprobante.pdf', subido_por=self.finan)

    def test_detalle_rechaza_lote_borrador(self):
        r = self.client.get(f'/pagos/{self.pago.pk}/')
        self.assertEqual(r.status_code, 302)  # redirect a la lista, no muestra la fila

    def test_subir_soporte_rechaza_lote_borrador(self):
        r = self.client.post(f'/pagos/{self.pago.pk}/soporte/', {'archivo': self._archivo()})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.pago.soportes.count(), 0)

    def test_eliminar_soporte_rechaza_lote_borrador(self):
        soporte = self._soporte_borrador()
        r = self.client.post(f'/pagos/soporte/{soporte.pk}/eliminar/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.pago.soportes.count(), 1)  # sigue existiendo

    def test_descargar_soporte_rechaza_lote_borrador(self):
        soporte = self._soporte_borrador()
        r = self.client.get(f'/pagos/soporte/{soporte.pk}/descargar/')
        self.assertEqual(r.status_code, 404)
