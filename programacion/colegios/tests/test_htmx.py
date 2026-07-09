"""
Tests — app: colegios (HTMX)
ajax_guardar_clase (fragmento vs JSON, bloqueos de borrado por informe/pago)
y el Kanban de pendientes.
"""
import json
from django.test import TestCase, Client
from django.contrib.auth.models import User
from datetime import date, time

from programacion.configuracion.models import Colegio, ColegioAnio, Profesor, Materia
from programacion.colegios.models import Bloque, Clase, Grado


# ── Tests HTMX — Fase 2 ──────────────────────────────────────────

class AjaxGuardarClaseHtmxTest(TestCase):
    """
    Verifica que ajax_guardar_clase devuelva fragmento HTML cuando lleva
    HX-Request: true, y JSON cuando no lo lleva (compatibilidad legacy).
    """

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.admin = User.objects.create_superuser('admin_htmx', password='pass')
        self.client.login(username='admin_htmx', password='pass')
        col = Colegio.objects.create(
            nombre='Col HTMX', departamento='Santander', ciudad='BGA'
        )
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)
        self.grado   = Grado.objects.create(nombre='11-1')
        self.bloque  = Bloque.objects.create(
            colegio=self.colegio, grado=self.grado,
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        )
        self.materia = Materia.objects.create(nombre='Física', color='#3498db')
        self.profesor = Profesor.objects.create(nombre='Luis', apellido='Ruiz')

    def _post(self, extra_headers=None, **data):
        payload = {
            'guardar_clase': '1',
            'bloque_id':     str(self.bloque.id),
            'fecha_clase':   '2026-05-15',
            'materia':       'Física',
            'profesor':      str(self.profesor.id),
            'unidad':        '1',
            'eliminar_clase': '0',
            'material_especial': '0',
            'tipo_especial': '',
            'libro_especial_id': '',
            'enlace_personalizado': '',
        }
        payload.update(data)
        headers = extra_headers or {}
        return self.client.post(
            f'/colegios/ajax/guardar-clase/{self.colegio.id}/',
            data=payload,
            **headers,
        )

    def test_sin_hx_request_devuelve_json(self):
        r = self._post()
        self.assertEqual(r.status_code, 200)
        self.assertIn('application/json', r['Content-Type'])
        data = json.loads(r.content)
        self.assertTrue(data['ok'])

    def test_con_hx_request_devuelve_html(self):
        r = self._post(extra_headers={'HTTP_HX_REQUEST': 'true'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/html', r['Content-Type'])
        self.assertIn(b'info-clase', r.content)

    def test_con_hx_request_html_incluye_bloque_id_y_fecha(self):
        r = self._post(extra_headers={'HTTP_HX_REQUEST': 'true'})
        self.assertIn(b'info-clase-' + str(self.bloque.id).encode(), r.content)
        self.assertIn(b'2026-05-15', r.content)

    def test_con_hx_request_incluye_hx_trigger_con_toast(self):
        r = self._post(extra_headers={'HTTP_HX_REQUEST': 'true'})
        trigger = r.get('HX-Trigger')
        self.assertIsNotNone(trigger)
        triggers = json.loads(trigger)
        self.assertIn('showToast', triggers)
        self.assertEqual(triggers['showToast']['level'], 'success')

    def test_eliminar_con_hx_request_devuelve_celda_vacia(self):
        # Primero crear la clase
        Clase.objects.create(
            colegio=self.colegio, bloque=self.bloque,
            fecha=date(2026, 5, 15),
            materia=self.materia, profesor=self.profesor, unidad='1',
        )
        r = self._post(
            extra_headers={'HTTP_HX_REQUEST': 'true'},
            eliminar_clase='1',
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content.strip(), b'')
        trigger = json.loads(r.get('HX-Trigger', '{}'))
        self.assertEqual(trigger.get('showToast', {}).get('level'), 'warning')

    def test_eliminar_clase_regular_ofrece_recalcular(self):
        # Eliminar una clase regular con clases futuras de la misma materia debe ofrecer
        # renumerar esas futuras desde la unidad que ocupaba la borrada (materia_quitada).
        Clase.objects.create(
            colegio=self.colegio, bloque=self.bloque, fecha=date(2026, 5, 15),
            materia=self.materia, profesor=self.profesor, unidad='1',
        )
        Clase.objects.create(
            colegio=self.colegio, bloque=self.bloque, fecha=date(2026, 5, 22),
            materia=self.materia, profesor=self.profesor, unidad='2',
        )
        r = self._post(extra_headers={'HTTP_HX_REQUEST': 'true'}, eliminar_clase='1')
        self.assertEqual(r.status_code, 200)
        trigger = json.loads(r.get('HX-Trigger', '{}'))
        self.assertIn('recalcular', trigger)
        item = trigger['recalcular'][0]
        self.assertEqual(item['motivo'], 'materia_quitada')
        self.assertEqual(item['unidad_inicio'], 1)
        self.assertEqual(item['n_clases'], 1)
        self.assertEqual(item['materia'], 'Física')

    def test_eliminar_clase_sin_futuras_no_ofrece_recalcular(self):
        # Sin clases futuras de la materia, eliminar no dispara el modal de recálculo.
        Clase.objects.create(
            colegio=self.colegio, bloque=self.bloque, fecha=date(2026, 5, 15),
            materia=self.materia, profesor=self.profesor, unidad='1',
        )
        r = self._post(extra_headers={'HTTP_HX_REQUEST': 'true'}, eliminar_clase='1')
        trigger = json.loads(r.get('HX-Trigger', '{}'))
        self.assertNotIn('recalcular', trigger)

    def test_eliminar_clase_con_informe_bloqueada(self):
        # Una clase con informe diligenciado NO debe poder borrarse: el informe es
        # rastro pedagógico y CASCADE lo eliminaría con la clase.
        from programacion.informes.models import Informe
        clase = Clase.objects.create(
            colegio=self.colegio, bloque=self.bloque, fecha=date(2026, 5, 15),
            materia=self.materia, profesor=self.profesor, unidad='1',
        )
        Informe.objects.create(
            profesor=self.profesor, clase=clase,
            colegio_nombre='Col HTMX', grado='11-1', fecha=date(2026, 5, 15),
            materia='Física', tematica='U1', material='Libro',
            actividades='Hizo cosas',
        )
        r = self._post(extra_headers={'HTTP_HX_REQUEST': 'true'}, eliminar_clase='1')
        self.assertEqual(r.status_code, 409)
        self.assertTrue(Clase.objects.filter(id=clase.id).exists())
        trigger = json.loads(r.get('HX-Trigger', '{}'))
        self.assertEqual(trigger.get('showToast', {}).get('level'), 'danger')
        self.assertIn('informe', trigger['showToast']['msg'].lower())

    def test_eliminar_clase_con_pago_enviado_bloqueada(self):
        # Clase con un pago ya enviado a financiera (lote ENVIADO) no se puede borrar.
        from programacion.pagos.models import PagoRealizado, LotePagos
        clase = Clase.objects.create(
            colegio=self.colegio, bloque=self.bloque, fecha=date(2026, 5, 15),
            materia=self.materia, profesor=self.profesor, unidad='1',
        )
        lote = LotePagos.objects.create(
            fecha_inicio=date(2026, 5, 11), fecha_fin=date(2026, 5, 15),
            estado=LotePagos.Estado.ENVIADO,
        )
        PagoRealizado.objects.create(
            lote=lote, profesor=self.profesor, colegio=self.colegio,
            fecha=date(2026, 5, 15), horas=2, valor=10000,
        )
        r = self._post(extra_headers={'HTTP_HX_REQUEST': 'true'}, eliminar_clase='1')
        self.assertEqual(r.status_code, 409)
        self.assertTrue(Clase.objects.filter(id=clase.id).exists())
        trigger = json.loads(r.get('HX-Trigger', '{}'))
        self.assertIn('pago', trigger['showToast']['msg'].lower())

    def test_eliminar_clase_con_pago_pagado_bloqueada(self):
        # Clase con un pago ya pagado (fecha_pago) tampoco se puede borrar, aunque el
        # pago no tenga lote (histórico).
        from django.utils import timezone
        from programacion.pagos.models import PagoRealizado
        clase = Clase.objects.create(
            colegio=self.colegio, bloque=self.bloque, fecha=date(2026, 5, 15),
            materia=self.materia, profesor=self.profesor, unidad='1',
        )
        PagoRealizado.objects.create(
            profesor=self.profesor, colegio=self.colegio,
            fecha=date(2026, 5, 15), horas=2, valor=10000,
            fecha_pago=timezone.now(),
        )
        r = self._post(extra_headers={'HTTP_HX_REQUEST': 'true'}, eliminar_clase='1')
        self.assertEqual(r.status_code, 409)
        self.assertTrue(Clase.objects.filter(id=clase.id).exists())

    def test_eliminar_clase_con_pago_borrador_permitida(self):
        # Un pago en BORRADOR es solo una preparación reversible: NO bloquea el borrado.
        from programacion.pagos.models import PagoRealizado, LotePagos
        clase = Clase.objects.create(
            colegio=self.colegio, bloque=self.bloque, fecha=date(2026, 5, 15),
            materia=self.materia, profesor=self.profesor, unidad='1',
        )
        lote = LotePagos.objects.create(
            fecha_inicio=date(2026, 5, 11), fecha_fin=date(2026, 5, 15),
            estado=LotePagos.Estado.BORRADOR,
        )
        PagoRealizado.objects.create(
            lote=lote, profesor=self.profesor, colegio=self.colegio,
            fecha=date(2026, 5, 15), horas=2, valor=10000,
        )
        r = self._post(extra_headers={'HTTP_HX_REQUEST': 'true'}, eliminar_clase='1')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Clase.objects.filter(id=clase.id).exists())

    def test_sin_permiso_devuelve_403(self):
        user_normal = User.objects.create_user('normal_htmx', password='pass')
        self.client.login(username='normal_htmx', password='pass')
        r = self._post(extra_headers={'HTTP_HX_REQUEST': 'true'})
        # ControlAccesoMiddleware redirige (302) antes de que la vista pueda devolver 403;
        # ambos implican acceso denegado.
        self.assertNotEqual(r.status_code, 200)

    def test_fecha_fuera_de_anio_devuelve_400(self):
        r = self._post(
            extra_headers={'HTTP_HX_REQUEST': 'true'},
            fecha_clase='2027-01-01',
        )
        self.assertEqual(r.status_code, 400)


class KanbanHTMXTest(TestCase):
    """Verifica que crear_tarea y cambiar_estado soporten HX-Request."""

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.admin = User.objects.create_superuser('admin_kanban', password='pass')
        self.client.login(username='admin_kanban', password='pass')

    def test_crear_tarea_htmx_devuelve_html_card(self):
        r = self.client.post(
            '/',
            {'crear_tarea': '1', 'titulo': 'Test HTMX tarea'},
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/html', r['Content-Type'])
        self.assertIn(b'Test HTMX tarea', r.content)
        self.assertIn(b'kanban-card', r.content)

    def test_crear_tarea_sin_htmx_redirige(self):
        r = self.client.post('/', {'crear_tarea': '1', 'titulo': 'Tarea normal'})
        self.assertEqual(r.status_code, 302)

    def test_cambiar_estado_htmx_devuelve_html_card(self):
        from programacion.pendientes.models import Tarea
        t = Tarea.objects.create(titulo='Tarea estado', creado_por=self.admin)
        r = self.client.post(
            f'/pendientes/cambiar-estado/{t.id}/gestion/',
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/html', r['Content-Type'])
        t.refresh_from_db()
        self.assertEqual(t.estado, 'gestion')
