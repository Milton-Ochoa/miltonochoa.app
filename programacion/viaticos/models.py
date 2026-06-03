import os

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify


class SolicitudViatico(models.Model):
    """Solicitud de viáticos de un docente para un viaje a un colegio.

    La crea el staff de programación y la gestiona financiera. Guarda FK a
    Profesor/Colegio y, además, un *snapshot* de sus datos identitarios
    (cédula, cuenta, código, nombre): la solicitud es un documento contable que
    debe conservar lo que valía al enviarla, aunque luego cambie el maestro.
    El servidor rellena el snapshot desde la FK al guardar (los inputs readonly
    del front son solo UX), así la integridad no depende del POST.
    """

    class Estado(models.TextChoices):
        ENVIADA  = 'ENVIADA',  'Enviada'
        DEVUELTA = 'DEVUELTA', 'Devuelta'
        APROBADA = 'APROBADA', 'Aprobada'
        PAGADA   = 'PAGADA',   'Pagada'

    profesor = models.ForeignKey('configuracion.Profesor', on_delete=models.PROTECT,
                                 related_name='viaticos')
    colegio  = models.ForeignKey('configuracion.Colegio',  on_delete=models.PROTECT,
                                 related_name='viaticos')

    # Snapshot bloqueado (lo rellena el servidor desde la FK al guardar):
    docente_nombre = models.CharField(max_length=200)
    docente_cedula = models.CharField(max_length=50,  blank=True)
    docente_cuenta = models.CharField(max_length=50,  blank=True)
    docente_banco  = models.CharField(max_length=100, blank=True)
    colegio_codigo = models.CharField(max_length=50,  blank=True)
    colegio_nombre = models.CharField(max_length=200)

    fecha_viaje   = models.DateField()
    fecha_regreso = models.DateField()
    observaciones = models.TextField(blank=True)

    estado            = models.CharField(max_length=10, choices=Estado.choices,
                                         default=Estado.ENVIADA)
    motivo_devolucion = models.TextField(blank=True)

    creado_por     = models.ForeignKey(User, on_delete=models.PROTECT,
                                       related_name='viaticos_creados')
    gestionado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='viaticos_gestionados')
    creado_en      = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    devuelto_en    = models.DateTimeField(null=True, blank=True)
    aprobado_en    = models.DateTimeField(null=True, blank=True)
    pagado_en      = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'prog_viaticos'
        ordering = ['-creado_en']
        verbose_name = 'Solicitud de viáticos'
        verbose_name_plural = 'Solicitudes de viáticos'

    def __str__(self):
        return f'Viático #{self.pk} — {self.docente_nombre} ({self.get_estado_display()})'

    def clean(self):
        if self.fecha_viaje and self.fecha_regreso and self.fecha_regreso < self.fecha_viaje:
            raise ValidationError({'fecha_regreso': 'La fecha de regreso no puede ser anterior a la de viaje.'})

    def aplicar_snapshot(self):
        """Copia los datos identitarios desde las FK al snapshot bloqueado.

        Fuente única de verdad del snapshot: la vista llama a esto antes de
        guardar para no confiar en los inputs readonly enviados por el cliente.
        """
        p, c = self.profesor, self.colegio
        self.docente_nombre = f'{p.nombre} {p.apellido or ""}'.strip()
        self.docente_cedula = p.documento or ''
        self.docente_cuenta = p.cuenta_bancaria or ''
        self.docente_banco  = p.banco or ''
        self.colegio_codigo = c.codigo or ''
        self.colegio_nombre = c.nombre

    @property
    def total(self):
        return sum(g.valor for g in self.gastos.all())


class GastoViatico(models.Model):
    """Una línea de gasto de una solicitud. La parte variable del formulario."""

    solicitud = models.ForeignKey(SolicitudViatico, on_delete=models.CASCADE,
                                  related_name='gastos')
    nombre = models.CharField(max_length=200)
    valor  = models.PositiveIntegerField()           # COP, enteros
    orden  = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'prog_viaticos_gastos'
        ordering = ['orden', 'id']

    def __str__(self):
        return f'{self.nombre}: {self.valor}'


def _soporte_upload_to(instance, filename):
    """Ruta/nombre limpio del soporte: ``viaticos/viatico-<docente>-<fecha><ext>``.

    Usa el snapshot del docente y la fecha de viaje para un nombre legible y
    estable. Con ``file_overwrite=False`` (S3) o el sufijo de FileSystemStorage,
    varios soportes del mismo viático reciben un sufijo único automático.
    """
    sol = instance.solicitud
    slug = slugify(sol.docente_nombre) or str(sol.pk)
    fecha = sol.fecha_viaje.isoformat() if sol.fecha_viaje else 'sin-fecha'
    ext = os.path.splitext(filename)[1].lower()
    return f'viaticos/viatico-{slug}-{fecha}{ext}'


class SoportePago(models.Model):
    """Archivo de soporte del pago de un viático (modelado aparte para permitir
    varios archivos por solicitud e historial: quién subió qué y cuándo).

    Reutilizable a futuro para otros pagos (profesores, monitores)."""

    solicitud = models.ForeignKey(SolicitudViatico, on_delete=models.CASCADE,
                                  related_name='soportes')
    archivo = models.FileField(upload_to=_soporte_upload_to)
    nombre_original = models.CharField(max_length=255, blank=True)
    subido_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='soportes_viatico')
    subido_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'prog_viaticos_soportes'
        ordering = ['-subido_en']
        verbose_name = 'Soporte de pago'
        verbose_name_plural = 'Soportes de pago'

    def __str__(self):
        return f'Soporte de viático #{self.solicitud_id} ({self.nombre_original or self.archivo.name})'
