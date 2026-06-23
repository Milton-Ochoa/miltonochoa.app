import io

from django.test import TestCase, Client
from django.contrib.auth.models import User, Group
from django.core.files.uploadedfile import SimpleUploadedFile

from openpyxl import Workbook, load_workbook

from programacion.monitores.models import ColegioSimulacro, Monitor


def _xlsx_bytes(filas, *, encabezados=('nombre', 'codigo', 'ciudad', 'departamento')):
    """Construye un .xlsx en memoria para los tests de carga masiva."""
    wb = Workbook()
    ws = wb.active
    if encabezados is not None:
        ws.append(list(encabezados))
    for fila in filas:
        ws.append(list(fila))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class ConfiguracionMonitoresViewTest(TestCase):
    """CRUD del catálogo de monitores desde Configuración (programación)."""

    URL = '/monitores/configuracion/'

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        User.objects.create_superuser(username='admin_mon', password='pass123')
        self.client.login(username='admin_mon', password='pass123')

    def test_listado_accesible(self):
        Monitor.objects.create(nombre='Ana', apellido='Pérez')
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Ana')

    def test_crear_monitor(self):
        self.client.post(self.URL, {
            'accion': 'add',
            'nombre': 'Carlos', 'apellido': 'Gómez',
            'documento': '12345', 'celular': '3001112233',
            'departamento': 'Santander', 'ciudad': 'Bucaramanga',
            'banco': Monitor.Banco.NEQUI, 'tipo_cuenta': Monitor.TipoCuenta.AHORROS,
            'cuenta_bancaria': '999',
        })
        m = Monitor.objects.get(documento='12345')
        self.assertEqual(m.nombre, 'Carlos')
        self.assertEqual(m.ciudad, 'Bucaramanga')
        self.assertTrue(m.activo)

    def test_crear_documento_duplicado_no_rompe(self):
        Monitor.objects.create(nombre='Uno', documento='555')
        self.client.post(self.URL, {
            'accion': 'add', 'nombre': 'Dos', 'documento': '555',
        })
        # El unique impide el segundo; solo queda uno.
        self.assertEqual(Monitor.objects.filter(documento='555').count(), 1)

    def test_editar_monitor(self):
        m = Monitor.objects.create(nombre='Luis', celular='300')
        self.client.post(self.URL, {
            'accion': 'edit', 'monitor_id': m.id,
            'nombre': 'Luis', 'celular': '311',
        })
        m.refresh_from_db()
        self.assertEqual(m.celular, '311')

    def test_toggle_activo(self):
        m = Monitor.objects.create(nombre='Pedro')
        self.assertTrue(m.activo)
        self.client.post(self.URL, {'accion': 'toggle_activo', 'monitor_id': m.id})
        m.refresh_from_db()
        self.assertFalse(m.activo)

    def test_eliminar_monitor(self):
        m = Monitor.objects.create(nombre='Borrar')
        self.client.post(self.URL, {'accion': 'del', 'monitor_id': m.id})
        self.assertFalse(Monitor.objects.filter(id=m.id).exists())

    def test_gate_anonimo_redirige(self):
        self.client.logout()
        resp = self.client.get(self.URL)
        self.assertNotEqual(resp.status_code, 200)


class MonitorModelTest(TestCase):
    def test_nombre_corto(self):
        m = Monitor(nombre='Juan Carlos', apellido='Pérez Gómez')
        self.assertEqual(m.nombre_corto, 'Juan Pérez')

    def test_nombre_corto_sin_apellido(self):
        m = Monitor(nombre='Ana')
        self.assertEqual(m.nombre_corto, 'Ana')


class StaffAreaAccesoTest(TestCase):
    """El staff del área (grupo area:programacion, no superusuario) accede."""

    URL = '/monitores/configuracion/'

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        u = User.objects.create_user(username='staff_mon', password='pass123')
        grupo, _ = Group.objects.get_or_create(name='area:programacion')
        u.groups.add(grupo)
        self.client.login(username='staff_mon', password='pass123')

    def test_staff_accede(self):
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 200)


class ColegioSimulacroViewTest(TestCase):
    """CRUD + carga masiva del catálogo de colegios de simulacro."""

    URL = '/monitores/colegios/'

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        User.objects.create_superuser(username='admin_cs', password='pass123')
        self.client.login(username='admin_cs', password='pass123')

    def test_listado_accesible(self):
        ColegioSimulacro.objects.create(nombre='Colegio Norte')
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Colegio Norte')

    def test_crear_colegio(self):
        self.client.post(self.URL, {
            'accion': 'add', 'nombre': 'Liceo Sur', 'codigo': 'LS-1',
            'departamento': 'Santander', 'ciudad': 'Bucaramanga',
        })
        c = ColegioSimulacro.objects.get(nombre='Liceo Sur')
        self.assertEqual(c.codigo, 'LS-1')
        self.assertEqual(c.ciudad, 'Bucaramanga')
        self.assertTrue(c.activo)

    def test_editar_colegio(self):
        c = ColegioSimulacro.objects.create(nombre='X', ciudad='A')
        self.client.post(self.URL, {
            'accion': 'edit', 'colegio_id': c.id, 'nombre': 'X', 'ciudad': 'B',
        })
        c.refresh_from_db()
        self.assertEqual(c.ciudad, 'B')

    def test_toggle_activo(self):
        c = ColegioSimulacro.objects.create(nombre='Toggle')
        self.client.post(self.URL, {'accion': 'toggle_activo', 'colegio_id': c.id})
        c.refresh_from_db()
        self.assertFalse(c.activo)

    def test_eliminar_colegio(self):
        c = ColegioSimulacro.objects.create(nombre='Borrar')
        self.client.post(self.URL, {'accion': 'del', 'colegio_id': c.id})
        self.assertFalse(ColegioSimulacro.objects.filter(id=c.id).exists())

    def test_gate_anonimo_redirige(self):
        self.client.logout()
        resp = self.client.get(self.URL)
        self.assertNotEqual(resp.status_code, 200)

    # ── Carga masiva ──────────────────────────────────────────
    def test_carga_masiva_crea(self):
        data = _xlsx_bytes([
            ('Colegio A', 'A1', 'Bogotá', 'Cundinamarca'),
            ('Colegio B', '', 'Cali', 'Valle del Cauca'),
        ])
        archivo = SimpleUploadedFile(
            'colegios.xlsx', data,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.client.post(self.URL, {'accion': 'cargar', 'archivo': archivo})
        self.assertEqual(ColegioSimulacro.objects.count(), 2)
        a = ColegioSimulacro.objects.get(nombre='Colegio A')
        self.assertEqual(a.codigo, 'A1')
        self.assertEqual(a.departamento, 'Cundinamarca')
        b = ColegioSimulacro.objects.get(nombre='Colegio B')
        self.assertIsNone(b.codigo)  # vacío → None

    def test_carga_masiva_idempotente(self):
        ColegioSimulacro.objects.create(nombre='Colegio A')
        data = _xlsx_bytes([
            ('Colegio A', '', '', ''),   # ya existe → omitido
            ('Colegio A', '', '', ''),   # duplicado dentro del archivo → omitido
            ('Colegio C', '', '', ''),   # nuevo
        ])
        archivo = SimpleUploadedFile('c.xlsx', data)
        self.client.post(self.URL, {'accion': 'cargar', 'archivo': archivo})
        self.assertEqual(ColegioSimulacro.objects.count(), 2)
        self.assertTrue(ColegioSimulacro.objects.filter(nombre='Colegio C').exists())

    def test_carga_masiva_columnas_desordenadas(self):
        # Encabezados en otro orden / mayúsculas → se mapean por nombre.
        data = _xlsx_bytes(
            [('Santander', 'Floridablanca', 'Colegio Z', 'CZ')],
            encabezados=('Departamento', 'Ciudad', 'Nombre', 'Codigo'))
        archivo = SimpleUploadedFile('z.xlsx', data)
        self.client.post(self.URL, {'accion': 'cargar', 'archivo': archivo})
        z = ColegioSimulacro.objects.get(nombre='Colegio Z')
        self.assertEqual(z.ciudad, 'Floridablanca')
        self.assertEqual(z.departamento, 'Santander')

    def test_carga_masiva_sin_columna_nombre(self):
        data = _xlsx_bytes([('A', 'B')], encabezados=('ciudad', 'codigo'))
        archivo = SimpleUploadedFile('bad.xlsx', data)
        self.client.post(self.URL, {'accion': 'cargar', 'archivo': archivo})
        self.assertEqual(ColegioSimulacro.objects.count(), 0)

    def test_carga_masiva_no_xlsx(self):
        archivo = SimpleUploadedFile('datos.csv', b'nombre,codigo\nA,B')
        self.client.post(self.URL, {'accion': 'cargar', 'archivo': archivo})
        self.assertEqual(ColegioSimulacro.objects.count(), 0)

    def test_descargar_plantilla(self):
        resp = self.client.post('/monitores/colegios/plantilla/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('spreadsheetml', resp['Content-Type'])
        wb = load_workbook(io.BytesIO(resp.content))
        encabezados = [c.value for c in wb.active[1]]
        self.assertEqual(encabezados, ['nombre', 'codigo', 'ciudad', 'departamento'])
