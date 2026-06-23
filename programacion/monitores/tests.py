from django.test import TestCase, Client
from django.contrib.auth.models import User, Group

from programacion.monitores.models import Monitor


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
