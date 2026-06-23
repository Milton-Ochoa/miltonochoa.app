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
