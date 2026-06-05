"""
Tests — app: pendientes (Kanban de tareas)
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User, Group

from programacion.pendientes.models import Tarea
from core.areas import GRUPO_STAFF_PROGRAMACION


class CambiarEstadoPermisosTest(TestCase):
    """El Kanban es un tablero de equipo: cualquier personal de programación
    (superusuario o staff de área) puede mover/editar tareas, no solo el creador."""

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.creador = User.objects.create_superuser('creador_k', password='pass123')
        self.tarea = Tarea.objects.create(titulo='Tarea ajena', creado_por=self.creador)
        grupo, _ = Group.objects.get_or_create(name=GRUPO_STAFF_PROGRAMACION)
        self.staff = User.objects.create_user('staff_k', password='pass123')
        self.staff.groups.add(grupo)

    def test_staff_de_area_puede_mover_tarea_ajena(self):
        # Regresión: el gate era is_superuser → el staff de área no podía mover
        # una tarea que no creó él mismo.
        self.assertFalse(self.staff.is_staff)
        self.client.login(username='staff_k', password='pass123')
        r = self.client.post(f'/pendientes/cambiar-estado/{self.tarea.id}/gestion/')
        self.assertEqual(r.status_code, 302)
        self.tarea.refresh_from_db()
        self.assertEqual(self.tarea.estado, 'gestion')

    def test_staff_de_area_puede_editar_tarea_ajena(self):
        self.client.login(username='staff_k', password='pass123')
        r = self.client.post(
            f'/pendientes/editar-tarea/{self.tarea.id}/',
            {'descripcion': 'Editada por staff'},
        )
        self.assertEqual(r.status_code, 302)
        self.tarea.refresh_from_db()
        self.assertEqual(self.tarea.descripcion, 'Editada por staff')

    def test_forastero_no_puede_mover(self):
        # Un usuario sin rol de programación no debe poder mover tareas: el
        # middleware lo desvía antes de llegar a la vista, así que el estado no cambia.
        User.objects.create_user('forastero_k', password='pass123')
        self.client.login(username='forastero_k', password='pass123')
        self.client.post(f'/pendientes/cambiar-estado/{self.tarea.id}/gestion/')
        self.tarea.refresh_from_db()
        self.assertEqual(self.tarea.estado, 'pendiente')  # no cambió
