"""
Tests — app: profesores
Sin modelos propios. Prueba utilidades y vistas de profesores/views.py
"""
import json
import shutil
import tempfile
from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.utils import timezone
from datetime import date, time, timedelta
from programacion.configuracion.models import Colegio, ColegioAnio, Profesor, NombreLibro, Materia, Unidad
from programacion.colegios.models import Asignacion, Bloque, Clase, ClasePersonalizada, Grado
from programacion.pagos.models import LotePagos, PagoRealizado, SoportePagoProfesor
from usuarios.models import UsuarioProfesor
from programacion.profesores.views import extraer_minutos, _resolver_unidad, _libro_para_fecha
from collections import defaultdict

# Soportes en disco local aislado en tmp: NUNCA tocar Supabase (igual que pagos/viáticos).
_STORAGE_LOCAL = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
_MEDIA_TMP_MIS_PAGOS = tempfile.mkdtemp()


# ── Utilidades ────────────────────────────────────────────────

class ExtraerMinutosProfesorTest(TestCase):
    # profesores/views.py usa try/except — devuelve 0 (no 9999) para inválidos

    def test_hora_manana(self):
        self.assertEqual(extraer_minutos('8:00 - 10:00'), 480)

    def test_hora_tarde(self):
        self.assertEqual(extraer_minutos('14:30 - 16:30'), 870)

    def test_hora_invalida_devuelve_cero(self):
        self.assertEqual(extraer_minutos('sin hora'), 0)

    def test_cadena_vacia_devuelve_cero(self):
        self.assertEqual(extraer_minutos(''), 0)


class ResolverUnidadTest(TestCase):

    def test_unidad_sin_objeto_devuelve_texto(self):
        material, label, link = _resolver_unidad('A', None)
        self.assertIsNone(material)
        self.assertEqual(label, 'A')
        self.assertEqual(link, '#')

    def test_unidad_numerica_con_unidad_usa_datos_del_objeto(self):
        # Simulamos un objeto Unidad con los atributos que usa _resolver_unidad
        class FakeUnidad:
            nombre = 'Lectura profunda'
            link   = 'https://example.com/u3'

        material, label, link = _resolver_unidad('3', FakeUnidad())
        self.assertIsNone(material)
        self.assertIn('Lectura profunda', label)
        self.assertEqual(link, 'https://example.com/u3')

    def test_unidad_numerica_sin_libro_devuelve_defaults(self):
        material, label, link = _resolver_unidad('5', None)
        self.assertIsNone(material)
        self.assertEqual(label, '5')
        self.assertEqual(link, '#')


class LibroParaFechaTest(TestCase):

    def setUp(self):
        col = Colegio.objects.create(nombre='Col Libro', departamento='Santander', ciudad='BGA')
        self.colegio = ColegioAnio.objects.create(colegio=col, anio=2026, activo=True)
        self.grado = Grado.objects.create(nombre='11-1')
        self.libro = NombreLibro.objects.create(nombre='Saberes 11 Oro')
        self.asig = Asignacion.objects.create(
            colegio=self.colegio, grado=self.grado, libro=self.libro,
            fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 12, 31),
        )
        self.mapa = defaultdict(list)
        self.mapa[(self.colegio.id, '11-1')].append(self.asig)

    def test_fecha_dentro_del_rango_devuelve_libro(self):
        r = _libro_para_fecha(self.mapa, self.colegio.id, '11-1', date(2026, 6, 15))
        self.assertEqual(r, 'Saberes 11 Oro')

    def test_fecha_fuera_del_rango_devuelve_sin_libro(self):
        r = _libro_para_fecha(self.mapa, self.colegio.id, '11-1', date(2025, 12, 31))
        self.assertEqual(r, 'Sin Libro')

    def test_colegio_o_grado_no_encontrado_devuelve_sin_libro(self):
        r = _libro_para_fecha(self.mapa, self.colegio.id, '9-1', date(2026, 3, 9))
        self.assertEqual(r, 'Sin Libro')


# ── Vistas ────────────────────────────────────────────────────

class VerHorarioViewTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        self.admin = User.objects.create_superuser(
            username='admin_prof', password='pass123'
        )
        self.profesor = Profesor.objects.create(nombre='Adrianis', apellido='Mercado')

    def test_no_autenticado_redirige_a_login(self):
        r = self.client.get('/profesores/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/usuarios/login/', r['Location'])

    def test_admin_puede_acceder_sin_profesor(self):
        self.client.login(username='admin_prof', password='pass123')
        r = self.client.get('/profesores/')
        self.assertEqual(r.status_code, 200)

    def test_admin_puede_acceder_con_profesor(self):
        self.client.login(username='admin_prof', password='pass123')
        r = self.client.get(f'/profesores/?profesor_id={self.profesor.id}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['profesor_sel'], str(self.profesor.id))

    def test_contexto_incluye_lista_de_profesores(self):
        self.client.login(username='admin_prof', password='pass123')
        r = self.client.get('/profesores/')
        self.assertIn('profesores', r.context)

    def test_usuario_profesor_no_puede_acceder_a_colegios(self):
        user = User.objects.create_user(username='adrianis', password='pass')
        UsuarioProfesor.objects.create(
            user=user, profesor=self.profesor
        )
        self.client.login(username='adrianis', password='pass')
        # El middleware bloquea /colegios/ y redirige a su horario
        r = self.client.get('/colegios/')
        self.assertEqual(r.status_code, 302)
        self.assertIn(f'profesor_id={self.profesor.id}', r['Location'])

    def _crear_staff_area(self, username):
        from django.contrib.auth.models import Group
        from core.areas import GRUPO_STAFF_PROGRAMACION
        grupo, _ = Group.objects.get_or_create(name=GRUPO_STAFF_PROGRAMACION)
        staff = User.objects.create_user(username, password='pass123')
        staff.groups.add(grupo)
        return staff

    def test_staff_de_area_ve_boton_personalizada(self):
        # Regresión: el staff de área (no is_staff) debe ver el botón "Personalizada"
        # y el selector de gestión, antes gateados por request.user.is_staff.
        staff = self._crear_staff_area('staff_prof')
        self.assertFalse(staff.is_staff)
        self.client.login(username='staff_prof', password='pass123')
        html = self.client.get(f'/profesores/?profesor_id={self.profesor.id}').content.decode()
        self.assertIn('Personalizada', html)

    def test_staff_de_area_puede_crear_personalizada(self):
        # Regresión: el POST de clases personalizadas estaba gateado por is_staff.
        self._crear_staff_area('staff_prof2')
        self.client.login(username='staff_prof2', password='pass123')
        r = self.client.post('/profesores/', {
            'guardar_personalizada': '1',
            'profesor_id': self.profesor.id,
            'estudiante':  'Juan',
            'ciudad':      'Bogotá',
            'mapa_link':   '',
            'fecha':       '2026-05-15',
            'hora_inicio': '08:00',
            'hora_fin':    '10:00',
            'grado':       '11-1',
            'material':    '',
            'materia':     'Matemáticas',
            'unidad':      '1',
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(
            ClasePersonalizada.objects.filter(
                profesor=self.profesor, estudiante='Juan').exists()
        )


class AjaxAsignaturasViewTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        User.objects.create_superuser(username='admin', password='pass')
        self.client.login(username='admin', password='pass')
        self.libro   = NombreLibro.objects.create(nombre='Saberes 11 Oro', activo=True)
        materia_obj  = Materia.objects.create(nombre='Lectura Crítica')
        Unidad.objects.create(
            libro=self.libro, materia=materia_obj,
            numero=1, nombre='Primera unidad', link='https://example.com/u1'
        )
        Unidad.objects.create(
            libro=self.libro, materia=materia_obj,
            numero=2, nombre='Segunda unidad', link='https://example.com/u2'
        )

    def test_devuelve_materias_para_material_existente(self):
        # material ahora es el id del libro (FK), no su nombre
        r = self.client.get(f'/profesores/ajax/asignaturas/?material={self.libro.id}')
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertIn('Lectura Crítica', data)

    def test_material_inexistente_devuelve_lista_vacia(self):
        r = self.client.get('/profesores/ajax/asignaturas/?material=999999')
        data = json.loads(r.content)
        self.assertEqual(data, [])

    def test_sin_parametro_devuelve_lista_vacia(self):
        r = self.client.get('/profesores/ajax/asignaturas/')
        data = json.loads(r.content)
        self.assertEqual(data, [])


class AjaxUnidadesViewTest(TestCase):

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        User.objects.create_superuser(username='admin', password='pass')
        self.client.login(username='admin', password='pass')
        self.libro   = NombreLibro.objects.create(nombre='Saberes 11 Oro', activo=True)
        materia_obj  = Materia.objects.create(nombre='Lectura Crítica')
        Unidad.objects.create(
            libro=self.libro, materia=materia_obj,
            numero=1, nombre='Primera', link='https://example.com'
        )

    def test_devuelve_unidades_para_material_y_materia_validos(self):
        # material ahora es el id del libro (FK), no su nombre
        r = self.client.get(
            f'/profesores/ajax/unidades/?material={self.libro.id}&materia=Lectura Crítica'
        )
        data = json.loads(r.content)
        self.assertTrue(len(data) > 0)
        self.assertIn('unidad', data[0])
        self.assertIn('nombre_unidad', data[0])

    def test_sin_parametros_devuelve_lista_vacia(self):
        r = self.client.get('/profesores/ajax/unidades/')
        data = json.loads(r.content)
        self.assertEqual(data, [])


# ── Portal del profesor: Mis pagos ────────────────────────────

class MisPagosViewTest(TestCase):
    """`/profesores/pagos/`: el profesor ve el estado de sus pagos por día de clases
    (pendiente/pagada), solo SUS filas y SIN montos en pesos."""

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        colegio = Colegio.objects.create(
            nombre='Colegio Central', departamento='Santander', ciudad='Bucaramanga')
        self.ca = ColegioAnio.objects.create(
            colegio=colegio, anio=date.today().year, valor_hora=40000)
        self.prof = Profesor.objects.create(nombre='Ana', apellido='Pérez')
        self.otro = Profesor.objects.create(nombre='Luis', apellido='Gómez')
        grado = Grado.objects.create(nombre='11-1')
        self.bloque = Bloque.objects.create(
            colegio=self.ca, grado=grado, hora_inicio=time(8, 0), hora_fin=time(10, 0))
        self.user = User.objects.create_user('ana_prof', password='pass')
        UsuarioProfesor.objects.create(user=self.user, profesor=self.prof)
        hoy = date.today()
        self.f_pagada    = hoy - timedelta(days=7)
        self.f_pendiente = hoy - timedelta(days=6)
        self.f_sin_fila  = hoy - timedelta(days=5)

    def _clase(self, profesor, fecha, **kw):
        return Clase.objects.create(
            colegio=self.ca, bloque=self.bloque, profesor=profesor, fecha=fecha, **kw)

    def _pago(self, fecha, **kw):
        return PagoRealizado.objects.create(
            profesor=self.prof, colegio=self.ca, fecha=fecha, horas=2, valor=80000, **kw)

    def test_clasifica_pagada_pendiente_y_sin_fila(self):
        self._clase(self.prof, self.f_pagada)
        self._clase(self.prof, self.f_pendiente)
        self._clase(self.prof, self.f_sin_fila)   # día aún sin fila materializada
        self._pago(self.f_pagada, fecha_pago=timezone.now())
        self._pago(self.f_pendiente)              # fila materializada pero no pagada
        self.client.login(username='ana_prof', password='pass')
        r = self.client.get('/profesores/pagos/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual([f['fecha'] for f in r.context['pagadas']], [self.f_pagada])
        self.assertEqual({f['fecha'] for f in r.context['pendientes']},
                         {self.f_pendiente, self.f_sin_fila})
        self.assertEqual(r.context['pagadas'][0]['horas'], 2)   # 8:00–10:00

    def test_solo_ve_sus_filas(self):
        self._clase(self.prof, self.f_pendiente)
        # Mismo día, otro profesor (en otro bloque: Clase es unique por (fecha, bloque)).
        otro_bloque = Bloque.objects.create(
            colegio=self.ca, grado=self.bloque.grado,
            hora_inicio=time(10, 0), hora_fin=time(12, 0))
        Clase.objects.create(colegio=self.ca, bloque=otro_bloque,
                             profesor=self.otro, fecha=self.f_pendiente)
        self.client.login(username='ana_prof', password='pass')
        r = self.client.get('/profesores/pagos/')
        self.assertEqual(len(r.context['pendientes']), 1)
        self.assertEqual(len(r.context['pagadas']), 0)

    def test_html_no_contiene_montos(self):
        # Contrato: ni el valor de la fila ni la tarifa del colegio aparecen jamás.
        self._clase(self.prof, self.f_pagada)
        self._clase(self.prof, self.f_pendiente)
        self._pago(self.f_pagada, fecha_pago=timezone.now())
        self.client.login(username='ana_prof', password='pass')
        html = self.client.get('/profesores/pagos/').content.decode()
        for monto in ('80000', '80.000', '80,000', '40000', '40.000', '40,000'):
            self.assertNotIn(monto, html)

    def test_cancelada_y_futura_no_aparecen(self):
        self._clase(self.prof, self.f_pendiente, cancelada=True)
        self._clase(self.prof, date.today() + timedelta(days=1))  # aún no dictada
        self.client.login(username='ana_prof', password='pass')
        r = self.client.get('/profesores/pagos/')
        self.assertEqual(len(r.context['pendientes']), 0)
        self.assertEqual(len(r.context['pagadas']), 0)

    def test_excluida_se_muestra_como_pendiente(self):
        # La exclusión es interna de programación: el profesor la ve "pendiente".
        self._clase(self.prof, self.f_pendiente)
        self._pago(self.f_pendiente, excluida=True)
        self.client.login(username='ana_prof', password='pass')
        r = self.client.get('/profesores/pagos/')
        self.assertEqual([f['fecha'] for f in r.context['pendientes']], [self.f_pendiente])

    def test_staff_redirige_a_pagos_lista(self):
        User.objects.create_superuser(username='admin_mp', password='pass')
        self.client.login(username='admin_mp', password='pass')
        r = self.client.get('/profesores/pagos/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/pagos/', r['Location'])

    def test_anonimo_redirige_a_login(self):
        r = self.client.get('/profesores/pagos/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/usuarios/login/', r['Location'])


@override_settings(MEDIA_ROOT=_MEDIA_TMP_MIS_PAGOS, STORAGES=_STORAGE_LOCAL)
class ProfesorSoporteDescargaTest(TestCase):
    """Descarga del soporte de pago gateada al DUEÑO: 404 (no 403) si no es suyo,
    para no revelar que el soporte existe."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_MEDIA_TMP_MIS_PAGOS, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.client = Client(HTTP_HOST='programacion.testserver')
        colegio = Colegio.objects.create(
            nombre='Colegio Central', departamento='Santander', ciudad='Bucaramanga')
        self.ca = ColegioAnio.objects.create(
            colegio=colegio, anio=date.today().year, valor_hora=40000)
        self.prof = Profesor.objects.create(nombre='Ana', apellido='Pérez')
        self.otro = Profesor.objects.create(nombre='Luis', apellido='Gómez')
        self.user_ana = User.objects.create_user('ana_prof', password='pass')
        UsuarioProfesor.objects.create(user=self.user_ana, profesor=self.prof)
        self.user_luis = User.objects.create_user('luis_prof', password='pass')
        UsuarioProfesor.objects.create(user=self.user_luis, profesor=self.otro)

        pago = PagoRealizado.objects.create(
            profesor=self.prof, colegio=self.ca, fecha=date.today() - timedelta(days=7),
            horas=2, valor=80000, fecha_pago=timezone.now())
        self.soporte = SoportePagoProfesor(pago=pago, nombre_original='comprobante.pdf')
        self.soporte.archivo.save('comprobante.pdf', ContentFile(b'%PDF-1.4 test'), save=True)

    def test_dueno_descarga_ok(self):
        self.client.login(username='ana_prof', password='pass')
        r = self.client.get(f'/profesores/pagos/soporte/{self.soporte.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('attachment', r['Content-Disposition'])
        r.close()   # FileResponse: liberar el handle del archivo en tmp

    def test_otro_profesor_recibe_404(self):
        self.client.login(username='luis_prof', password='pass')
        r = self.client.get(f'/profesores/pagos/soporte/{self.soporte.pk}/')
        self.assertEqual(r.status_code, 404)

    def test_staff_recibe_404_en_endpoint_de_profesor(self):
        # El staff tiene su propio proxy (pago_soporte_descargar); este es solo del dueño.
        User.objects.create_superuser(username='admin_sop', password='pass')
        self.client.login(username='admin_sop', password='pass')
        r = self.client.get(f'/profesores/pagos/soporte/{self.soporte.pk}/')
        self.assertEqual(r.status_code, 404)

    def test_anonimo_redirige_a_login(self):
        r = self.client.get(f'/profesores/pagos/soporte/{self.soporte.pk}/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/usuarios/login/', r['Location'])

    def test_pagina_muestra_soporte_y_enlaces_de_descarga(self):
        # La clase del día pagado debe existir para que la fila aparezca en la página.
        grado = Grado.objects.create(nombre='11-1')
        bloque = Bloque.objects.create(
            colegio=self.ca, grado=grado, hora_inicio=time(8, 0), hora_fin=time(10, 0))
        Clase.objects.create(colegio=self.ca, bloque=bloque, profesor=self.prof,
                             fecha=self.soporte.pago.fecha)
        self.client.login(username='ana_prof', password='pass')
        html = self.client.get('/profesores/pagos/').content.decode()
        self.assertIn(f'/profesores/pagos/soporte/{self.soporte.pk}/', html)
        self.assertIn(self.soporte.nombre_mostrar, html)