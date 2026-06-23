import os

from django.contrib.auth.models import User
from django.db import models
from django.utils.text import slugify

# Reutilizamos los choices bancarios del catálogo de profesores (mismo dominio,
# mismos bancos colombianos) en lugar de duplicar las listas. Conviven en
# Profesor porque ese fue el primer modelo en necesitarlos; al ser TextChoices
# planos (valor=etiqueta) no acoplan a monitores con la lógica del profesor.
from programacion.configuracion.models import Profesor


class Monitor(models.Model):
    """Persona que vigila salones durante un simulacro (no es profesor).

    Versión simplificada de ``Profesor``: solo los datos necesarios para
    contactarlo y pagarle. El ``documento`` es obligatorio para los exports de
    pago, pero ``blank``/``null`` para no bloquear el alta cuando aún no se tiene.
    """

    # Alias de los choices de Profesor para usarlos en el form/admin sin importar
    # Profesor en cada sitio (Monitor.Banco / Monitor.TipoCuenta).
    Banco = Profesor.Banco
    TipoCuenta = Profesor.TipoCuenta

    nombre          = models.CharField(max_length=200, verbose_name="Nombre(s)")
    apellido        = models.CharField(max_length=200, blank=True, null=True,
                                       verbose_name="Apellido(s)")
    documento       = models.CharField(max_length=20, unique=True, blank=True, null=True,
                                       verbose_name="Cédula / Documento")
    celular         = models.CharField(max_length=20, blank=True, null=True,
                                       verbose_name="Celular")
    departamento    = models.CharField(max_length=100, blank=True, null=True,
                                       verbose_name="Departamento")
    ciudad          = models.CharField(max_length=100, blank=True, null=True,
                                       verbose_name="Ciudad")
    banco           = models.CharField(max_length=100, blank=True, null=True,
                                       choices=Banco.choices, verbose_name="Banco")
    tipo_cuenta     = models.CharField(max_length=20, blank=True, null=True,
                                       choices=TipoCuenta.choices, verbose_name="Tipo de Cuenta")
    cuenta_bancaria = models.CharField(max_length=50, blank=True, null=True,
                                       verbose_name="Cuenta Bancaria")
    activo          = models.BooleanField(default=True, verbose_name="Activo")

    class Meta:
        db_table = 'prog_monitores'
        verbose_name = 'Monitor'
        verbose_name_plural = 'Monitores'

    @staticmethod
    def nombre_corto_de(nombre, apellido):
        """Primer nombre + primer apellido a partir de strings sueltos.

        Para listados masivos que traen nombre/apellido vía ``.values()`` sin
        instanciar el modelo (acepta None/'' en cualquiera de los dos).
        """
        primer_nombre   = nombre.split()[0] if nombre else ''
        primer_apellido = apellido.split()[0] if apellido else ''
        return f"{primer_nombre} {primer_apellido}".strip()

    @property
    def nombre_corto(self):
        """Primer nombre + primer apellido. Solo display, no existe en BD.

        NUNCA usar en lookups de queryset; para listas masivas usar
        ``Monitor.nombre_corto_de(nombre, apellido)``.
        """
        return self.nombre_corto_de(self.nombre, self.apellido)

    def __str__(self):
        return self.nombre_corto


class ColegioSimulacro(models.Model):
    """Colegio donde se realiza un simulacro.

    Catálogo **independiente** de ``configuracion.Colegio``: los simulacros se
    hacen en instituciones que no necesariamente están en el sistema, así que
    se admite alta individual y **carga masiva por Excel**. Solo datos de
    identificación/ubicación; sin calendario, años ni cronograma.
    """

    nombre       = models.CharField(max_length=200, verbose_name="Nombre")
    codigo       = models.CharField(max_length=50, blank=True, null=True,
                                    verbose_name="Código")
    ciudad       = models.CharField(max_length=100, blank=True, null=True,
                                    verbose_name="Ciudad")
    departamento = models.CharField(max_length=100, blank=True, null=True,
                                    verbose_name="Departamento")
    activo       = models.BooleanField(default=True, verbose_name="Activo")

    class Meta:
        db_table = 'prog_simulacro_colegios'
        verbose_name = 'Colegio de simulacro'
        verbose_name_plural = 'Colegios de simulacro'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Simulacro(models.Model):
    """Un simulacro (examen de práctica) realizado en un colegio.

    A diferencia de las clases, en un simulacro no van profesores sino
    **monitores** (vigilan los salones). El ``valor`` es lo que se le paga a
    **cada** monitor asignado (2 monitores = 2 pagos de ese valor). Los monitores
    se asignan vía ``AsignacionMonitor`` (0..N por simulacro).
    """

    class Jornada(models.TextChoices):
        MANANA   = 'MANANA', 'Mañana'
        TARDE    = 'TARDE', 'Tarde'
        TODO_DIA = 'TODO_DIA', 'Todo el día'

    # SET_NULL + snapshot: el documento del simulacro sobrevive al borrado del
    # colegio del catálogo (patrón CancelacionClase). El nombre se congela en save().
    colegio        = models.ForeignKey(ColegioSimulacro, on_delete=models.SET_NULL,
                                       null=True, blank=True, related_name='simulacros',
                                       verbose_name="Colegio")
    colegio_nombre = models.CharField(max_length=200, blank=True,
                                      verbose_name="Colegio (snapshot)")
    fecha          = models.DateField(verbose_name="Fecha")
    # M2M al catálogo global de grados (nunca texto libre).
    grados         = models.ManyToManyField('colegios.Grado', blank=True,
                                            related_name='simulacros',
                                            verbose_name="Grados")
    jornada        = models.CharField(max_length=10, choices=Jornada.choices,
                                      default=Jornada.TODO_DIA, verbose_name="Jornada")
    valor          = models.PositiveIntegerField(default=0,
                                                 verbose_name="Valor por monitor (COP)")
    monitores      = models.ManyToManyField(Monitor, through='AsignacionMonitor',
                                            related_name='simulacros', blank=True,
                                            verbose_name="Monitores")
    observaciones  = models.TextField(blank=True, verbose_name="Observaciones")
    creado_en      = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'prog_simulacros'
        verbose_name = 'Simulacro'
        verbose_name_plural = 'Simulacros'
        ordering = ['-fecha']

    def save(self, *args, **kwargs):
        # Congela el nombre del colegio mientras la FK exista (sobrevive al borrado).
        if self.colegio_id:
            self.colegio_nombre = self.colegio.nombre
        super().save(*args, **kwargs)

    @property
    def nombre_colegio(self):
        """Nombre a mostrar: la FK viva o el snapshot si el colegio se borró."""
        return self.colegio.nombre if self.colegio_id else self.colegio_nombre

    def __str__(self):
        return f"Simulacro {self.nombre_colegio} {self.fecha:%d/%m/%Y}"


class AsignacionMonitor(models.Model):
    """Through del M2M ``Simulacro.monitores``: un monitor asignado a un simulacro.

    FK ``monitor`` con ``PROTECT`` para no perder el rastro de a quién se le debe
    un pago; el simulacro con ``CASCADE`` (si se borra el simulacro, sus
    asignaciones se van con él). Un monitor no puede asignarse dos veces al mismo
    simulacro (``unique_together``).
    """

    simulacro = models.ForeignKey(Simulacro, on_delete=models.CASCADE,
                                  related_name='asignaciones', verbose_name="Simulacro")
    monitor   = models.ForeignKey(Monitor, on_delete=models.PROTECT,
                                  related_name='asignaciones', verbose_name="Monitor")
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'prog_simulacros_monitores'
        verbose_name = 'Asignación de monitor'
        verbose_name_plural = 'Asignaciones de monitor'
        unique_together = ('simulacro', 'monitor')

    def __str__(self):
        return f"{self.monitor} → {self.simulacro}"


# ─────────────────────────────────────────────────────────────
# PAGOS DE MONITORES — espejo del flujo de profesores (programacion.pagos),
# pero con fuente = simulacros (AsignacionMonitor), no clases. Modelos PROPIOS
# (no se generalizan los de profesores: ese flujo tiene gate-por-informe, que
# monitores NO tiene). Mismo ciclo BORRADOR→ENVIADO por lote semanal y PAGADO
# por fila (`fecha_pago`), para reusar los partials/Excel en las fases de UI.
# ─────────────────────────────────────────────────────────────


class LoteMonitores(models.Model):
    """Lote semanal de pagos a monitores: ancla el ciclo de revisión.

    Espejo de ``pagos.LotePagos``: programación **prepara** el borrador de una
    semana (materializa las filas ``PagoMonitor`` desde las asignaciones de
    simulacros), las revisa y las **envía** a financiera. El estado vive aquí, por
    semana —no por fila— para que "Enviar" sea un solo UPDATE; ``PAGADO`` es
    ortogonal y vive por fila (``PagoMonitor.fecha_pago``).

    Flujo de una sola vía ``BORRADOR → ENVIADO`` (el envío es definitivo por lote).
    Pueden coexistir N lotes ENVIADO por semana pero **máximo un BORRADOR**
    (constraint parcial): al enviar, las filas excluidas se desacoplan
    (``lote=None``) y un "Preparar pendientes" posterior las re-adopta.
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
        related_name='lotes_monitores_enviados', verbose_name='Enviado por',
    )
    creado_en      = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table            = 'prog_monitores_pagos_lotes'
        ordering            = ['-fecha_inicio']
        verbose_name        = 'Lote de pagos de monitores'
        verbose_name_plural = 'Lotes de pagos de monitores'
        constraints = [
            models.UniqueConstraint(
                fields=['fecha_inicio', 'fecha_fin'],
                condition=models.Q(estado='BORRADOR'),
                name='unique_lote_monitores_borrador_por_semana',
            ),
        ]

    def __str__(self):
        return f'Lote monitores {self.fecha_inicio}–{self.fecha_fin} ({self.get_estado_display()})'

    @property
    def enviado(self):
        return self.estado == self.Estado.ENVIADO


class PagoMonitor(models.Model):
    """Fila base de un pago a un monitor por su asignación a un simulacro.

    A diferencia de profesores (agrupa por día/colegio), aquí la unidad natural es
    la **asignación**: un monitor por simulacro = un pago de ``simulacro.valor``.
    El constraint único ``(monitor, simulacro)`` lo garantiza. ``fecha`` y ``valor``
    se desnormalizan del simulacro para preservar el histórico y la semana aunque
    cambien luego.

    - ``valor`` = ``simulacro.valor`` al materializar (no hay horas ni tarifa/hora).
    - ``excluida`` = la fila no se envía a financiera (no se borra → re-preparar es
      idempotente).
    - ``fecha_pago``/``marcado_por`` = los fija financiera al pagar (null = no pagada).
    - Filas históricas: ``lote IS NULL AND fecha_pago IS NOT NULL``.
    """

    lote      = models.ForeignKey(
        LoteMonitores, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='filas', verbose_name='Lote',
    )
    monitor   = models.ForeignKey(
        Monitor, on_delete=models.PROTECT,
        related_name='pagos', verbose_name='Monitor',
    )
    simulacro = models.ForeignKey(
        # PROTECT: no borrar un simulacro que ya generó pagos.
        Simulacro, on_delete=models.PROTECT,
        related_name='pagos', verbose_name='Simulacro',
    )
    fecha     = models.DateField(verbose_name='Fecha del simulacro')
    valor     = models.IntegerField(verbose_name='Valor del simulacro (COP)')
    excluida  = models.BooleanField(default=False, verbose_name='Excluida del envío')
    fecha_pago  = models.DateTimeField(null=True, blank=True, verbose_name='Fecha de pago')
    marcado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='pagos_monitores_marcados', verbose_name='Marcado por',
    )

    class Meta:
        db_table            = 'prog_monitores_pagos'
        unique_together     = ('monitor', 'simulacro')
        ordering            = ['-fecha', 'monitor__nombre']
        verbose_name        = 'Pago de monitor'
        verbose_name_plural = 'Pagos de monitores'

    def __str__(self):
        return f"{self.monitor} | {self.simulacro} | {self.fecha} | ${self.total:,}"

    @property
    def valor_base(self):
        """Valor base efectivo (monitores no editan el valor a mano → es ``valor``).
        Existe para que los partials/Excel compartidos lo lean igual que en profesores."""
        return self.valor

    @property
    def total_extras(self):
        return sum(e.valor for e in self.extras.all())

    @property
    def total(self):
        return self.valor_base + self.total_extras

    @property
    def pagada(self):
        return self.fecha_pago is not None


class ExtraPagoMonitor(models.Model):
    """Costo extra del desglose de un pago de monitor (espejo de ``pagos.ExtraPago``)."""

    pago     = models.ForeignKey(PagoMonitor, on_delete=models.CASCADE,
                                 related_name='extras')
    concepto = models.CharField(max_length=200)
    valor    = models.PositiveIntegerField()           # COP, enteros
    orden    = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table            = 'prog_monitores_pagos_extras'
        ordering            = ['orden', 'id']
        verbose_name        = 'Costo extra de pago de monitor'
        verbose_name_plural = 'Costos extra de pago de monitor'

    def __str__(self):
        return f'{self.concepto}: {self.valor}'


def _monitor_soporte_upload_to(instance, filename):
    """Ruta/nombre limpio del soporte: ``pagos-monitores/pago-<monitor>-<fecha><ext>``.

    Espejo de ``pagos._pago_soporte_upload_to``: nombre del monitor + fecha del
    simulacro para un nombre legible y estable. El storage añade un sufijo único
    cuando hay varios soportes del mismo pago.
    """
    pago = instance.pago
    slug = slugify(pago.monitor.nombre_corto) or str(pago.pk)
    fecha = pago.fecha.isoformat() if pago.fecha else 'sin-fecha'
    ext = os.path.splitext(filename)[1].lower()
    return f'pagos-monitores/pago-{slug}-{fecha}{ext}'


class SoportePagoMonitor(models.Model):
    """Comprobante de un pago liquidado a un monitor (FK a ``PagoMonitor``).

    Espejo de ``pagos.SoportePagoProfesor``: varios archivos por pago e historial de
    quién subió qué y cuándo. Lo sube/elimina **financiera**; programación lo ve en
    solo lectura. El ``FileField`` usa ``STORAGES['default']`` (disco en dev, Supabase
    en prod); la descarga la proxia una vista protegida (fase de financiera).
    """

    pago = models.ForeignKey(PagoMonitor, on_delete=models.CASCADE,
                             related_name='soportes')
    archivo = models.FileField(upload_to=_monitor_soporte_upload_to)
    nombre_original = models.CharField(max_length=255, blank=True)
    subido_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='soportes_pago_monitor')
    subido_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'prog_monitores_pagos_soportes'
        ordering = ['-subido_en']
        verbose_name = 'Soporte de pago a monitor'
        verbose_name_plural = 'Soportes de pago a monitor'

    def __str__(self):
        return f'Soporte de pago de monitor #{self.pago_id} ({self.nombre_original or self.archivo.name})'

    @property
    def nombre_mostrar(self):
        """Nombre visible: el nombre real en storage (refleja el renombrado del
        ``upload_to`` y el sufijo único), no el ``nombre_original`` subido."""
        if self.archivo and self.archivo.name:
            return os.path.basename(self.archivo.name)
        return self.nombre_original or 'archivo'
