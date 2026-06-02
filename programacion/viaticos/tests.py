"""
Tests — app: viaticos
Modelos: SolicitudViatico, GastoViatico
"""
from datetime import date

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

from programacion.configuracion.models import Colegio, Profesor
from programacion.viaticos.models import GastoViatico, SolicitudViatico


class SolicitudViaticoModelTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('staff', 'staff@x.com', 'x')
        self.profesor = Profesor.objects.create(
            nombre='Juan', apellido='Pérez', documento='123',
            cuenta_bancaria='999-888',
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
        self.assertEqual(s.colegio_codigo, 'COL-1')
        self.assertEqual(s.colegio_nombre, 'Colegio Norte')

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
