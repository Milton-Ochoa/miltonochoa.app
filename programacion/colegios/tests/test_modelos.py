"""
Tests — app: colegios (modelos y utilidades)
Utilidades: extraer_numero_grado, ordenar_grados
Modelos: Bloque, Asignacion, Clase (calendarios A y B), ClasePersonalizada
"""
from django.test import TestCase
from datetime import date, time

from programacion.configuracion.models import Colegio, ColegioAnio, Profesor, NombreLibro, Materia
from programacion.colegios.models import Bloque, Asignacion, Clase, ClasePersonalizada, Grado
from programacion.colegios.utils import (
    extraer_numero_grado,
    ordenar_grados,
)


# ── Utilidades ────────────────────────────────────────────────

class ExtraerNumeroGradoTest(TestCase):

    def test_grado_con_guion(self):
        self.assertEqual(extraer_numero_grado('11-1'), 11)

    def test_grado_simple(self):
        self.assertEqual(extraer_numero_grado('10'), 10)

    def test_sin_numero_devuelve_cero(self):
        self.assertEqual(extraer_numero_grado('sin número'), 0)


class OrdenarGradosTest(TestCase):

    def test_grados_tradicionales_descendente(self):
        grados = ['10-1', '11-1', '9-1']
        resultado = ordenar_grados(grados)
        self.assertEqual(resultado[0], '11-1')
        self.assertEqual(resultado[-1], '9-1')

    def test_grados_especiales_van_al_final(self):
        grados = ['11-1', 'Grupo 1', '10-1']
        resultado = ordenar_grados(grados)
        self.assertIn('Grupo 1', resultado)
        self.assertEqual(resultado[-1], 'Grupo 1')


# ── Modelos ───────────────────────────────────────────────────

class BloqueModelTest(TestCase):

    def setUp(self):
        col = Colegio.objects.create(
            nombre='Colegio Test', departamento='Santander', ciudad='Bogotá'
        )
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)
        self.grado = Grado.objects.create(nombre='11-1')

    def test_str_incluye_grado_y_hora(self):
        b = Bloque.objects.create(
            colegio=self.colegio, grado=self.grado,
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        )
        self.assertIn('11-1', str(b))

    def test_propiedad_hora_formato_ampm(self):
        b = Bloque.objects.create(
            colegio=self.colegio, grado=self.grado,
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        )
        self.assertIn('AM', b.hora)

    def test_propiedad_duracion_minutos(self):
        b = Bloque.objects.create(
            colegio=self.colegio, grado=self.grado,
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        )
        self.assertEqual(b.duracion_minutos, 120)


class AsignacionModelTest(TestCase):

    def setUp(self):
        col = Colegio.objects.create(
            nombre='Col Asig', departamento='Antioquia', ciudad='Cali'
        )
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)
        self.grado = Grado.objects.create(nombre='11-1')

    def test_fechas_se_autocompletan_si_no_se_proveen(self):
        libro = NombreLibro.objects.create(nombre='Saberes 11 Oro')
        asig = Asignacion.objects.create(
            colegio=self.colegio, grado=self.grado, libro=libro
        )
        anio = date.today().year
        self.assertEqual(asig.fecha_inicio, date(anio, 1, 1))
        self.assertEqual(asig.fecha_fin, date(anio, 12, 31))

    def test_fechas_manuales_no_se_sobreescriben(self):
        libro = NombreLibro.objects.create(nombre='Saberes 11 Oro')
        asig = Asignacion.objects.create(
            colegio=self.colegio, grado=self.grado, libro=libro,
            fecha_inicio=date(2026, 3, 1), fecha_fin=date(2026, 6, 30),
        )
        self.assertEqual(asig.fecha_inicio, date(2026, 3, 1))
        self.assertEqual(asig.fecha_fin, date(2026, 6, 30))

    def test_str_incluye_colegio_grado_libro(self):
        libro = NombreLibro.objects.create(nombre='Conceptos 10')
        asig = Asignacion.objects.create(
            colegio=self.colegio, grado=self.grado, libro=libro
        )
        r = str(asig)
        self.assertIn('Col Asig', r)
        self.assertIn('11-1', r)
        self.assertIn('Conceptos 10', r)


class ClaseModelTest(TestCase):

    def setUp(self):
        col = Colegio.objects.create(
            nombre='Col Clase', departamento='Cundinamarca', ciudad='BGA'
        )
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)
        self.grado = Grado.objects.create(nombre='11-1')
        self.bloque = Bloque.objects.create(
            colegio=self.colegio, grado=self.grado,
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        )

    def test_valores_por_defecto(self):
        c = Clase.objects.create(
            colegio=self.colegio, bloque=self.bloque, fecha=date.today()
        )
        self.assertFalse(c.cancelada)
        self.assertFalse(c.es_evento)
        self.assertIsNone(c.profesor)

    def test_unique_together_fecha_y_bloque(self):
        from django.db import IntegrityError
        hoy = date.today()
        Clase.objects.create(colegio=self.colegio, bloque=self.bloque, fecha=hoy)
        with self.assertRaises(IntegrityError):
            Clase.objects.create(colegio=self.colegio, bloque=self.bloque, fecha=hoy)

    def test_misma_fecha_diferente_bloque_es_valido(self):
        grado2  = Grado.objects.create(nombre='10-1')
        bloque2 = Bloque.objects.create(
            colegio=self.colegio, grado=grado2,
            hora_inicio=time(10, 30), hora_fin=time(12, 0),
        )
        hoy = date.today()
        Clase.objects.create(colegio=self.colegio, bloque=self.bloque,  fecha=hoy)
        Clase.objects.create(colegio=self.colegio, bloque=bloque2, fecha=hoy)
        self.assertEqual(Clase.objects.filter(fecha=hoy).count(), 2)

    def test_clean_rechaza_fecha_de_otro_anio(self):
        from django.core.exceptions import ValidationError
        clase = Clase(
            colegio=self.colegio, bloque=self.bloque,
            fecha=date(2027, 3, 15),
        )
        with self.assertRaises(ValidationError):
            clase.clean()

    def test_clean_acepta_fecha_del_mismo_anio(self):
        clase = Clase(
            colegio=self.colegio, bloque=self.bloque,
            fecha=date(2026, 6, 15),
        )
        clase.clean()  # No debe lanzar excepción


class ClaseCalendarioBTest(TestCase):
    """Validación de fechas de clase para un colegio Calendario B (ago→jun)."""

    def setUp(self):
        col = Colegio.objects.create(
            nombre='Col B', departamento='Santander', ciudad='BGA',
            calendario=Colegio.Calendario.B,
        )
        # anio=2025 (ancla) → ventana ago-2025 … jun-2026
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2025, activo=True)
        self.grado = Grado.objects.create(nombre='11-1')
        self.bloque = Bloque.objects.create(
            colegio=self.colegio, grado=self.grado,
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        )

    def test_rango_cruza_dos_anios(self):
        self.assertEqual(self.colegio.rango, (date(2025, 8, 1), date(2026, 6, 30)))

    def test_clean_acepta_fecha_del_primer_tramo(self):
        # septiembre 2025 (ago–dic del año ancla)
        Clase(colegio=self.colegio, bloque=self.bloque,
              fecha=date(2025, 9, 15)).clean()

    def test_clean_acepta_fecha_del_segundo_tramo(self):
        # marzo 2026 (ene–jun del año+1)
        Clase(colegio=self.colegio, bloque=self.bloque,
              fecha=date(2026, 3, 15)).clean()

    def test_clean_rechaza_fecha_antes_de_la_ventana(self):
        from django.core.exceptions import ValidationError
        # julio 2025, antes del inicio
        with self.assertRaises(ValidationError):
            Clase(colegio=self.colegio, bloque=self.bloque,
                  fecha=date(2025, 7, 15)).clean()

    def test_clean_rechaza_fecha_despues_de_la_ventana(self):
        from django.core.exceptions import ValidationError
        # julio 2026, después del fin
        with self.assertRaises(ValidationError):
            Clase(colegio=self.colegio, bloque=self.bloque,
                  fecha=date(2026, 7, 1)).clean()

    def test_cohortes_no_se_mezclan(self):
        # Dos periodos del mismo colegio B: cada clase queda particionada por su FK.
        sig = ColegioAnio.objects.create(
            colegio=self.colegio.colegio, anio=2026, activo=True
        )
        bloque_sig = Bloque.objects.create(
            colegio=sig, grado=self.grado,
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        )
        c1 = Clase.objects.create(colegio=self.colegio, bloque=self.bloque,
                                  fecha=date(2025, 9, 15))
        c2 = Clase.objects.create(colegio=sig, bloque=bloque_sig,
                                  fecha=date(2026, 9, 15))
        self.assertEqual(list(Clase.objects.filter(colegio=self.colegio)), [c1])
        self.assertEqual(list(Clase.objects.filter(colegio=sig)), [c2])

    def test_asignacion_autocompleta_con_ventana_b(self):
        libro = NombreLibro.objects.create(nombre='Saberes B')
        asig = Asignacion.objects.create(
            colegio=self.colegio, grado=self.grado, libro=libro
        )
        self.assertEqual(asig.fecha_inicio, date(2025, 8, 1))
        self.assertEqual(asig.fecha_fin, date(2026, 6, 30))


class ClasePersonalizadaModelTest(TestCase):

    def setUp(self):
        self.profesor = Profesor.objects.create(nombre='Ana', apellido='García')

    def test_str_incluye_estudiante_y_profesor(self):
        grado = Grado.objects.create(nombre='10-1')
        materia = Materia.objects.create(nombre='Lectura Crítica')
        libro = NombreLibro.objects.create(nombre='Conceptos 10')
        cp = ClasePersonalizada.objects.create(
            profesor=self.profesor, estudiante='Col San Pedro',
            fecha=date.today(), hora_inicio=time(14, 0), hora_fin=time(16, 0),
            grado=grado, libro=libro, materia=materia, unidad='2',
        )
        self.assertIn('Col San Pedro', str(cp))
        self.assertIn('Ana', str(cp))

    def test_ciudad_default_bucaramanga(self):
        grado = Grado.objects.create(nombre='11-1')
        materia = Materia.objects.create(nombre='Mate')
        libro = NombreLibro.objects.create(nombre='Libro A')
        cp = ClasePersonalizada.objects.create(
            profesor=self.profesor, estudiante='Col X',
            fecha=date.today(), hora_inicio=time(8, 0), hora_fin=time(10, 0),
            grado=grado, libro=libro, materia=materia, unidad='1',
        )
        self.assertEqual(cp.ciudad, 'Bucaramanga')

    def test_propiedad_hora_devuelve_rango(self):
        grado = Grado.objects.create(nombre='9-1')
        materia = Materia.objects.create(nombre='Ciencias')
        libro = NombreLibro.objects.create(nombre='Libro B')
        cp = ClasePersonalizada.objects.create(
            profesor=self.profesor, estudiante='Col Y',
            fecha=date.today(), hora_inicio=time(14, 0), hora_fin=time(16, 0),
            grado=grado, libro=libro, materia=materia, unidad='1',
        )
        self.assertEqual(cp.hora, '2:00 PM - 4:00 PM')
