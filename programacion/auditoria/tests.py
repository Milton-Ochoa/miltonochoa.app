from django.test import TestCase, Client
from django.contrib.auth.models import User

from programacion.auditoria.models import AlertaAuditoria
from programacion.configuracion.models import Colegio, ColegioAnio


class AlertaAuditoriaModelTest(TestCase):

    def setUp(self):
        col = Colegio.objects.create(
            nombre='Test Col', departamento='Bogota D.C.', ciudad='Bogotá',
        )
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)

    def test_crear_alerta(self):
        alerta = AlertaAuditoria.objects.create(
            tipo=AlertaAuditoria.Tipo.DUPLICADO,
            huella='abc123',
            mensaje='Duplicado de prueba',
            colegio=self.colegio,
        )
        self.assertTrue(alerta.vigente)
        self.assertIsNone(alerta.resuelto_en)

    def test_huella_unica(self):
        AlertaAuditoria.objects.create(
            tipo=AlertaAuditoria.Tipo.DUPLICADO,
            huella='unica',
            mensaje='Primera',
        )
        with self.assertRaises(Exception):
            AlertaAuditoria.objects.create(
                tipo=AlertaAuditoria.Tipo.DUPLICADO,
                huella='unica',
                mensaje='Duplicada',
            )

    def test_str(self):
        alerta = AlertaAuditoria(
            tipo=AlertaAuditoria.Tipo.CONFLICTO,
            mensaje='Conflicto de prueba',
        )
        self.assertIn('Choque de Profesor', str(alerta))


class ListaAlertasViewTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.admin = User.objects.create_superuser(
            username='admin_audit', password='pass123',
        )

    def test_no_autenticado_redirige(self):
        r = self.client.get('/auditoria/')
        self.assertEqual(r.status_code, 302)

    def test_admin_puede_acceder(self):
        self.client.login(username='admin_audit', password='pass123')
        r = self.client.get('/auditoria/')
        self.assertEqual(r.status_code, 200)

    def test_filtro_vigentes(self):
        self.client.login(username='admin_audit', password='pass123')
        AlertaAuditoria.objects.create(
            tipo=AlertaAuditoria.Tipo.SECUENCIA,
            huella='vig1', mensaje='Vigente', vigente=True,
        )
        AlertaAuditoria.objects.create(
            tipo=AlertaAuditoria.Tipo.SECUENCIA,
            huella='res1', mensaje='Resuelta', vigente=False,
        )
        r = self.client.get('/auditoria/')
        self.assertEqual(len(r.context['alertas']), 1)
