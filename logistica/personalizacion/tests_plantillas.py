"""Tests de la Fase 2 (CRUD de plantillas): gates, subida (validación dura +
aviso suave de campos), borrado (fila + archivo) y descarga proxiada.

Mismo arnés de archivos que `logistica/inventario/tests_movimientos.py`:
`Client(HTTP_HOST='logistica.testserver')` + storage LOCAL en tmp
(override de MEDIA_ROOT/STORAGES) → NUNCA tocan Supabase.
"""
import shutil
import tempfile

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from core.areas import GRUPO_STAFF_FINANCIERA, GRUPO_STAFF_LOGISTICA

from .generar import campos_esperados
from .models import PlantillaPersonalizacion
from .tests_generar import crear_plantilla_bytes

_STORAGE_LOCAL = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
_MEDIA_TMP = tempfile.mkdtemp()


def _pdf(campos):
    """SimpleUploadedFile de un PDF con AcroForm sembrado con los `campos`."""
    return SimpleUploadedFile('plantilla.pdf', crear_plantilla_bytes(campos),
                              content_type='application/pdf')


@override_settings(MEDIA_ROOT=_MEDIA_TMP, STORAGES=_STORAGE_LOCAL)
class _BasePlantillasTest(TestCase):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_MEDIA_TMP, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.client = Client(HTTP_HOST='logistica.testserver')
        self.user = User.objects.create_user(username='logis', password='pass')
        self.user.groups.add(Group.objects.get(name=GRUPO_STAFF_LOGISTICA))
        self.client.login(username='logis', password='pass')

    def _mensajes(self, response):
        return [str(m) for m in response.context['messages']]


class GatesPlantillasTest(_BasePlantillasTest):

    def test_anonimo_redirigido(self):
        c = Client(HTTP_HOST='logistica.testserver')
        self.assertEqual(c.get('/personalizacion/').status_code, 302)

    def test_usuario_de_otra_area_no_entra(self):
        u = User.objects.create_user(username='finan', password='pass')
        u.groups.add(Group.objects.get(name=GRUPO_STAFF_FINANCIERA))
        c = Client(HTTP_HOST='logistica.testserver')
        c.login(username='finan', password='pass')
        self.assertEqual(c.get('/personalizacion/').status_code, 302)

    def test_staff_logistica_ve_la_lista(self):
        self.assertEqual(self.client.get('/personalizacion/').status_code, 200)


class SubirPlantillaTest(_BasePlantillasTest):

    def test_sube_pdf_completo_sin_aviso(self):
        campos = campos_esperados('SIMULACRO')
        r = self.client.post('/personalizacion/plantillas/subir/', {
            'nombre': 'Simulacro GO', 'tipo': 'SIMULACRO',
            'archivo': _pdf(campos),
        }, follow=True)
        plantilla = PlantillaPersonalizacion.objects.get()
        self.assertEqual(plantilla.nombre, 'Simulacro GO')
        self.assertEqual(plantilla.tipo, 'SIMULACRO')
        self.assertEqual(plantilla.subido_por, self.user)
        self.assertTrue(plantilla.archivo.name.endswith('.pdf'))
        mensajes = self._mensajes(r)
        self.assertTrue(any('guardada' in m for m in mensajes))
        self.assertFalse(any('faltan campos' in m for m in mensajes))

    def test_aviso_suave_si_faltan_campos(self):
        # PDF con formulario pero sin los campos que el tipo espera.
        r = self.client.post('/personalizacion/plantillas/subir/', {
            'nombre': 'Incompleta', 'tipo': 'PENSAR',
            'archivo': _pdf(['CampoCualquiera']),
        }, follow=True)
        self.assertEqual(PlantillaPersonalizacion.objects.count(), 1)
        self.assertTrue(any('faltan campos' in m for m in self._mensajes(r)))

    def test_rechaza_no_pdf(self):
        archivo = SimpleUploadedFile('notas.txt', b'no soy un pdf',
                                     content_type='text/plain')
        r = self.client.post('/personalizacion/plantillas/subir/', {
            'nombre': 'Mala', 'tipo': 'SIMULACRO', 'archivo': archivo,
        }, follow=True)
        self.assertFalse(PlantillaPersonalizacion.objects.exists())
        self.assertTrue(any('PDF' in m for m in self._mensajes(r)))

    def test_rechaza_sin_nombre(self):
        r = self.client.post('/personalizacion/plantillas/subir/', {
            'nombre': '', 'tipo': 'SIMULACRO',
            'archivo': _pdf(campos_esperados('SIMULACRO')),
        }, follow=True)
        self.assertFalse(PlantillaPersonalizacion.objects.exists())


class EliminarPlantillaTest(_BasePlantillasTest):
    """Eliminar es SOLO del superusuario: el template oculta el botón al staff
    y la vista rechaza el POST (el check del server es la barrera real)."""

    def setUp(self):
        super().setUp()
        self.admin_client = Client(HTTP_HOST='logistica.testserver')
        User.objects.create_superuser(username='admin', password='pass')
        self.admin_client.login(username='admin', password='pass')

    def _crear(self):
        self.client.post('/personalizacion/plantillas/subir/', {
            'nombre': 'Borrable', 'tipo': 'SIMULACRO',
            'archivo': _pdf(campos_esperados('SIMULACRO')),
        })
        return PlantillaPersonalizacion.objects.get()

    def test_admin_elimina_fila_y_archivo(self):
        plantilla = self._crear()
        storage, name = plantilla.archivo.storage, plantilla.archivo.name
        self.assertTrue(storage.exists(name))
        r = self.admin_client.post(
            f'/personalizacion/plantillas/{plantilla.pk}/eliminar/', follow=True)
        self.assertFalse(PlantillaPersonalizacion.objects.exists())
        self.assertFalse(storage.exists(name))
        self.assertTrue(any('eliminada' in m for m in self._mensajes(r)))

    def test_staff_no_puede_eliminar(self):
        plantilla = self._crear()
        r = self.client.post(
            f'/personalizacion/plantillas/{plantilla.pk}/eliminar/', follow=True)
        self.assertTrue(PlantillaPersonalizacion.objects.exists())
        self.assertTrue(any('administrador' in m for m in self._mensajes(r)))

    def test_staff_no_ve_el_boton_de_eliminar(self):
        plantilla = self._crear()
        url_eliminar = f'/personalizacion/plantillas/{plantilla.pk}/eliminar/'
        r = self.client.get('/personalizacion/')
        self.assertNotContains(r, url_eliminar)
        r = self.admin_client.get('/personalizacion/')
        self.assertContains(r, url_eliminar)

    def test_eliminar_get_no_permitido(self):
        plantilla = self._crear()
        r = self.admin_client.get(
            f'/personalizacion/plantillas/{plantilla.pk}/eliminar/')
        self.assertEqual(r.status_code, 405)
        self.assertTrue(PlantillaPersonalizacion.objects.exists())


class DescargarPlantillaTest(_BasePlantillasTest):

    def test_descarga_proxiada(self):
        self.client.post('/personalizacion/plantillas/subir/', {
            'nombre': 'Descargable', 'tipo': 'SIMULACRO',
            'archivo': _pdf(campos_esperados('SIMULACRO')),
        })
        plantilla = PlantillaPersonalizacion.objects.get()
        r = self.client.get(
            f'/personalizacion/plantillas/{plantilla.pk}/descargar/')
        self.assertEqual(r.status_code, 200)
        contenido = b''.join(r.streaming_content)
        self.assertTrue(contenido.startswith(b'%PDF'))
        self.assertIn('attachment', r['Content-Disposition'])
