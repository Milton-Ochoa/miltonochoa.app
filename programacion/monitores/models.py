from django.db import models

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
