"""Tests del área financiera — pagos de clases a profesores (Fase 2).

Acceso por subdominio, marcar/desmarcar (crea/borra `PagoRealizado`) y la descarga
de Excel. El cálculo semanal (clases → filas) lo cubren los tests de programación;
aquí se valida la gestión propia de financiera y su gate de área.
"""
from datetime import date

from django.test import TestCase, Client
from django.contrib.auth.models import User, Group

from core.areas import GRUPO_STAFF_FINANCIERA, GRUPO_STAFF_PROGRAMACION
from programacion.configuracion.models import Colegio, ColegioAnio, Profesor
from programacion.exportar.models import PagoRealizado


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
        self.assertContains(r, 'Relación de Pagos')

    def test_lista_rechaza_usuario_solo_programacion(self):
        u = User.objects.create_user(username='prog', password='pass')
        u.groups.add(self.grupo_prog)
        self.client.login(username='prog', password='pass')
        r = self.client.get('/pagos/')
        self.assertNotEqual(r.status_code, 200)  # middleware lo saca del subdominio

    # ── Marcar / desmarcar ────────────────────────────────────
    def test_marcar_crea_pago(self):
        self._login_financiera()
        r = self.client.post('/pagos/marcar/', {
            'accion': 'marcar',
            'profesor_id': self.profesor.id,
            'colegio_id': self.colegio_anio.id,
            'fecha': '2025-03-14',
            'horas': '2',
            'valor': '80000',
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])
        pago = PagoRealizado.objects.get(profesor=self.profesor, colegio=self.colegio_anio)
        self.assertEqual(pago.valor, 80000)
        self.assertEqual(pago.marcado_por, self.finan)

    def test_marcar_es_idempotente(self):
        self._login_financiera()
        datos = {
            'accion': 'marcar', 'profesor_id': self.profesor.id,
            'colegio_id': self.colegio_anio.id, 'fecha': '2025-03-14',
            'horas': '2', 'valor': '80000',
        }
        self.client.post('/pagos/marcar/', datos)
        self.client.post('/pagos/marcar/', datos)  # segundo no duplica
        self.assertEqual(PagoRealizado.objects.count(), 1)

    def test_desmarcar_borra_pago(self):
        self._login_financiera()
        PagoRealizado.objects.create(
            profesor=self.profesor, colegio=self.colegio_anio,
            fecha=date(2025, 3, 14), horas=2, valor=80000)
        r = self.client.post('/pagos/marcar/', {
            'accion': 'desmarcar',
            'profesor_id': self.profesor.id,
            'colegio_id': self.colegio_anio.id,
            'fecha': '2025-03-14',
        })
        self.assertTrue(r.json()['ok'])
        self.assertEqual(PagoRealizado.objects.count(), 0)

    def test_marcar_requiere_financiera(self):
        # Sin login → no debe crear nada (redirige a login/apex).
        r = self.client.post('/pagos/marcar/', {
            'accion': 'marcar', 'profesor_id': self.profesor.id,
            'colegio_id': self.colegio_anio.id, 'fecha': '2025-03-14',
            'horas': '2', 'valor': '80000',
        })
        self.assertNotEqual(r.status_code, 200)
        self.assertEqual(PagoRealizado.objects.count(), 0)

    # ── Exportar ──────────────────────────────────────────────
    def test_exportar_devuelve_xlsx(self):
        self._login_financiera()
        r = self.client.post('/pagos/exportar/', {
            'fecha_inicio': '2025-03-10', 'fecha_fin': '2025-03-14', 'tab': 'pendiente',
        })
        self.assertEqual(r.status_code, 200)
        self.assertIn('spreadsheetml', r['Content-Type'])
        self.assertIn('attachment', r['Content-Disposition'])
