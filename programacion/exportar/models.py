import os

from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify
from programacion.configuracion.models import Profesor, ColegioAnio


class PagoRealizado(models.Model):
    """Registro inmutable de un pago liquidado a un profesor por un día de clases.

    El constraint único (profesor, colegio, fecha) garantiza que la misma clase
    no se marque como pagada dos veces. El endpoint ajax_marcar_pago usa
    get_or_create para respetar este constraint sin lanzar excepción.

    El campo 'valor' se calcula en la vista como horas × ColegioAnio.valor_hora
    y se guarda desnormalizado para preservar el valor histórico aunque cambie
    la tarifa del colegio en el futuro.
    """

    profesor    = models.ForeignKey(
        Profesor, on_delete=models.PROTECT,
        related_name='pagos_realizados', verbose_name='Profesor',
    )
    colegio     = models.ForeignKey(
        # PROTECT evita borrar un ColegioAnio que ya tiene pagos registrados.
        ColegioAnio, on_delete=models.PROTECT,
        related_name='pagos_realizados', verbose_name='Colegio/Año',
    )
    fecha       = models.DateField(verbose_name='Fecha de la clase')
    horas       = models.FloatField(verbose_name='Horas dictadas')
    valor       = models.IntegerField(verbose_name='Valor pagado (COP)')
    fecha_pago  = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de pago')
    marcado_por = models.ForeignKey(
        # SET_NULL permite que el registro sobreviva si se elimina el usuario admin.
        User, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='pagos_marcados', verbose_name='Marcado por',
    )

    class Meta:
        db_table            = 'prog_pagos'
        unique_together     = ('profesor', 'colegio', 'fecha')
        ordering            = ['-fecha', 'profesor__nombre']
        verbose_name        = 'Pago Realizado'
        verbose_name_plural = 'Pagos Realizados'

    def __str__(self):
        return f"{self.profesor} | {self.colegio} | {self.fecha} | ${self.valor:,}"


def _pago_soporte_upload_to(instance, filename):
    """Ruta/nombre limpio del soporte de un pago: ``pagos/pago-<docente>-<fecha><ext>``.

    Espejo de ``viaticos._soporte_upload_to``: usa el nombre corto del docente y la
    fecha de la clase para un nombre legible y estable. Con ``file_overwrite=False``
    (S3) o el sufijo de FileSystemStorage, varios soportes del mismo pago reciben un
    sufijo único automático.
    """
    pago = instance.pago
    slug = slugify(pago.profesor.nombre_corto) or str(pago.pk)
    fecha = pago.fecha.isoformat() if pago.fecha else 'sin-fecha'
    ext = os.path.splitext(filename)[1].lower()
    return f'pagos/pago-{slug}-{fecha}{ext}'


class SoportePagoProfesor(models.Model):
    """Comprobante de un pago liquidado a un profesor (FK a `PagoRealizado`).

    Espejo de `viaticos.SoportePago`: varios archivos por pago e historial de quién
    subió qué y cuándo. Lo sube/elimina **financiera**; programación lo ve en solo
    lectura. El `FileField` usa el backend de `STORAGES['default']` (disco en dev,
    Supabase Storage/S3 en prod); la descarga la proxia una vista protegida.
    """

    pago = models.ForeignKey(PagoRealizado, on_delete=models.CASCADE,
                             related_name='soportes')
    archivo = models.FileField(upload_to=_pago_soporte_upload_to)
    nombre_original = models.CharField(max_length=255, blank=True)
    subido_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='soportes_pago')
    subido_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'prog_pagos_soportes'
        ordering = ['-subido_en']
        verbose_name = 'Soporte de pago a profesor'
        verbose_name_plural = 'Soportes de pago a profesor'

    def __str__(self):
        return f'Soporte de pago #{self.pago_id} ({self.nombre_original or self.archivo.name})'
