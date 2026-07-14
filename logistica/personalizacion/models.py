import os

from django.contrib.auth.models import User
from django.db import models
from django.utils.text import slugify


def _plantilla_upload_to(instance, filename):
    """``logistica/personalizacion/<tipo>-<slug-nombre><ext>`` (patrón
    `_adjunto_entrada_upload_to`: nombre legible y estable; el storage añade
    sufijo único si se repite)."""
    base, ext = os.path.splitext(filename)
    slug = slugify(instance.nombre) or slugify(base) or 'plantilla'
    return f'logistica/personalizacion/{instance.tipo.lower()}-{slug}{ext.lower()}'


class PlantillaPersonalizacion(models.Model):
    """Plantilla PDF con formulario AcroForm que se rellena por estudiante.

    Tres tipos con distinta forma de rellenado (ver `personalizacion.generar`):
    SIMULACRO (un estudiante por hoja, mismo dato arriba y abajo), PENSAR (dos
    estudiantes por hoja + número de prueba) y MP (Martes de Prueba: tres
    estudiantes por hoja + número de prueba; código de colegio, año y código de
    estudiante vienen del Excel). Se guardan permanentemente y se gestionan
    libremente (subir/borrar); los estudiantes NO viven en BD (se suben por
    Excel en cada generación).
    """

    class Tipo(models.TextChoices):
        SIMULACRO = 'SIMULACRO', 'Simulacro'
        PENSAR    = 'PENSAR',    'Pensar'
        MP        = 'MP',        'MP'

    nombre     = models.CharField(max_length=150)
    tipo       = models.CharField(max_length=10, choices=Tipo.choices)
    archivo    = models.FileField(upload_to=_plantilla_upload_to)
    subido_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                   blank=True,
                                   related_name='plantillas_personalizacion')
    subido_en  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'log_plantillas_personalizacion'
        ordering = ['tipo', 'nombre']
        verbose_name = 'Plantilla de personalización'
        verbose_name_plural = 'Plantillas de personalización'

    def __str__(self):
        return f'{self.get_tipo_display()} · {self.nombre}'
