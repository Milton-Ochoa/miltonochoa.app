import os

from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify
from programacion.configuracion.models import Profesor, ColegioAnio


class LotePagos(models.Model):
    """Lote semanal de pagos a profesores: ancla el ciclo de revisión.

    Programación **prepara** el borrador de una semana (materializa las filas
    `PagoRealizado` calculadas desde las clases), las revisa/edita y luego la
    **envía** a financiera. El estado vive aquí, por semana —no por fila— para que
    "Enviar" sea un solo UPDATE; el estado `PAGADO` es ortogonal y vive por fila
    (`PagoRealizado.fecha_pago`).

    Flujo de una sola vía: `BORRADOR → ENVIADO` — **el envío es definitivo POR LOTE**
    (no existe "des-enviar" ni "devolver"). Financiera **solo ve** las filas de lotes
    `ENVIADO`. La semana se ancla en su lunes–domingo canónico (semana completa: hay
    profesores que dictan en fin de semana, y con lunes–viernes esas clases no se
    materializaban).

    Pueden coexistir **N lotes ENVIADO por semana** (cada envío congela exactamente lo
    que se envió) pero **máximo un BORRADOR** (constraint parcial): al enviar, las
    filas no enviables (excluidas o con clases sin informe) se desacoplan
    (`lote=None`) y un "Preparar pendientes" posterior las re-adopta a un BORRADOR
    nuevo, de modo que pueden ir en un envío posterior.
    """

    class Estado(models.TextChoices):
        BORRADOR = 'BORRADOR', 'Borrador'
        ENVIADO  = 'ENVIADO',  'Enviado'

    fecha_inicio   = models.DateField(verbose_name='Inicio de la semana')
    fecha_fin      = models.DateField(verbose_name='Fin de la semana')
    estado         = models.CharField(max_length=10, choices=Estado.choices,
                                      default=Estado.BORRADOR)
    enviado_en     = models.DateTimeField(null=True, blank=True)
    enviado_por    = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='lotes_pago_enviados', verbose_name='Enviado por',
    )
    creado_en      = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table            = 'prog_pagos_lotes'
        ordering            = ['-fecha_inicio']
        verbose_name        = 'Lote de pagos'
        verbose_name_plural = 'Lotes de pagos'
        constraints = [
            # Varios ENVIADO por semana (re-envíos de filas rezagadas), pero un solo
            # BORRADOR: es el lote "vivo" que preparar/enviar sincronizan.
            models.UniqueConstraint(
                fields=['fecha_inicio', 'fecha_fin'],
                condition=models.Q(estado='BORRADOR'),
                name='unique_lote_borrador_por_semana',
            ),
        ]

    def __str__(self):
        return f'Lote {self.fecha_inicio}–{self.fecha_fin} ({self.get_estado_display()})'

    @property
    def enviado(self):
        return self.estado == self.Estado.ENVIADO


class PagoRealizado(models.Model):
    """Fila base de un pago a un profesor por un día de clases `(profesor, colegio, fecha)`.

    El constraint único `(profesor, colegio, fecha)` garantiza una sola fila base por
    día; los costos extra (desplazamiento, etc.) cuelgan en `ExtraPago` (desglose).

    Ciclo de vida (vía el `lote`): programación la **materializa** en BORRADOR al
    preparar la semana, la revisa (override de `valor_base_editado`, `excluida`,
    extras) y la envía; financiera la **paga** fijando `fecha_pago`/`marcado_por`.

    - `valor` = valor base calculado (horas × `ColegioAnio.valor_hora`), desnormalizado
      para preservar el histórico aunque cambie la tarifa.
    - `valor_base_editado` = override manual de programación (null = usar `valor`).
    - `excluida` = la fila no se envía a financiera (no se borra, para que re-preparar
      sea idempotente).
    - `fecha_pago`/`marcado_por` = los fija financiera al pagar (null = no pagada).
    - Filas históricas (anteriores a este flujo): `lote IS NULL AND fecha_pago IS NOT NULL`.
    """

    lote        = models.ForeignKey(
        LotePagos, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='filas', verbose_name='Lote',
    )
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
    valor       = models.IntegerField(verbose_name='Valor base calculado (COP)')
    valor_base_editado = models.IntegerField(
        null=True, blank=True, verbose_name='Valor base editado (COP)',
    )
    excluida    = models.BooleanField(default=False, verbose_name='Excluida del envío')
    # null = no pagada; financiera lo fija al marcar (antes era auto_now_add, pero la
    # fila ahora nace en BORRADOR sin estar pagada).
    fecha_pago  = models.DateTimeField(null=True, blank=True, verbose_name='Fecha de pago')
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
        return f"{self.profesor} | {self.colegio} | {self.fecha} | ${self.total:,}"

    @property
    def valor_base(self):
        """Valor base efectivo: el override de programación si existe, si no el calculado."""
        return self.valor_base_editado if self.valor_base_editado is not None else self.valor

    @property
    def total_extras(self):
        return sum(e.valor for e in self.extras.all())

    @property
    def total(self):
        """Total a pagar: valor base (posiblemente editado) + costos extra del desglose."""
        return self.valor_base + self.total_extras

    @property
    def pagada(self):
        return self.fecha_pago is not None


class ExtraPago(models.Model):
    """Costo extra del desglose de un pago (espejo de `viaticos.GastoViatico`).

    Lo agrega programación durante la revisión (p. ej. "Desplazamiento") y queda atado
    al profesor vía la fila base (`pago`), de modo que financiera ve el desglose y los
    datos bancarios salen de la fila base."""

    pago     = models.ForeignKey(PagoRealizado, on_delete=models.CASCADE,
                                 related_name='extras')
    concepto = models.CharField(max_length=200)
    valor    = models.PositiveIntegerField()           # COP, enteros
    orden    = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table            = 'prog_pagos_extras'
        ordering            = ['orden', 'id']
        verbose_name        = 'Costo extra de pago'
        verbose_name_plural = 'Costos extra de pago'

    def __str__(self):
        return f'{self.concepto}: {self.valor}'


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

    @property
    def nombre_mostrar(self):
        """Nombre visible del adjunto: el nombre real en storage (refleja el renombrado
        de `_pago_soporte_upload_to` y el sufijo único), no el nombre original subido."""
        if self.archivo and self.archivo.name:
            return os.path.basename(self.archivo.name)
        return self.nombre_original or 'archivo'
