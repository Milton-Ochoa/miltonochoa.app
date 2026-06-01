import re
from django.db import models
from django.core.exceptions import ValidationError
from datetime import date


def _anio_actual():
    """Valor por defecto callable para ColegioAnio.anio — evita que el año quede
    hardcodeado en la migración y siempre toma el año de ejecución."""
    return date.today().year


# Validación de color hex a nivel de módulo para reutilizarla en modelo y vistas.
# El color se usa en inline styles de templates; sin validación un valor arbitrario
# podría romper el CSS o introducir XSS vía expression() en IE antiguo.
_HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?$')


def _validate_hex_color(value: str) -> None:
    """Valida que el valor sea un color hexadecimal CSS válido (#RGB o #RRGGBB).

    Se usa como validator de campo en Materia.color para bloquear valores que
    rompan inline styles o introduzcan XSS.
    """
    if not _HEX_COLOR_RE.match(value):
        raise ValidationError(
            '%(value)s no es un color hexadecimal válido (ej: #e74c3c o #f00)',
            params={'value': value},
        )


class Materia(models.Model):
    """Asignatura académica. El color se usa en badges y celdas de cronograma."""

    nombre = models.CharField(max_length=100, unique=True, verbose_name="Nombre de la Materia")
    color  = models.CharField(
        max_length=7,
        default='#6c757d',
        verbose_name="Color",
        help_text="Color hexadecimal, ej: #e74c3c",
        validators=[_validate_hex_color],
    )

    class Meta:
        ordering            = ['nombre']
        verbose_name        = "Materia"
        verbose_name_plural = "Materias"

    def __str__(self):
        return self.nombre


class NombreLibro(models.Model):
    """Libro físico o material pedagógico del catálogo global.

    El flag `es_material_asignado` separa dos categorías de libros con flujos distintos:
    - False (normal): aparece en el selector de Asignaciones por grado.
    - True (material asignado): se excluye de Asignaciones y solo aparece en el modal
      de clase como "Material Asignado". Permite registrar clases con material extra
      sin interferir con el libro principal del grado.
    """

    nombre               = models.CharField(max_length=200, unique=True, verbose_name="Nombre del Libro")
    activo               = models.BooleanField(default=True, verbose_name="Activo")
    es_material_asignado = models.BooleanField(default=False, verbose_name="Es Material Asignado")

    class Meta:
        ordering            = ['nombre']
        verbose_name        = "Libro"
        verbose_name_plural = "Libros"

    def __str__(self):
        return self.nombre


class Unidad(models.Model):
    """Unidad temática de un libro para una materia específica.

    La tripleta (libro, materia, numero) es única: un libro puede tener varias
    materias y cada materia tiene su propia numeración de unidades.
    El link apunta al material digital de la unidad (Google Drive, etc.).
    """

    libro   = models.ForeignKey(
        NombreLibro, on_delete=models.CASCADE,
        related_name='unidades', verbose_name="Libro"
    )
    materia = models.ForeignKey(
        # PROTECT evita borrar accidentalmente una materia que tiene unidades activas
        Materia, on_delete=models.PROTECT,
        related_name='unidades', verbose_name="Materia"
    )
    numero  = models.PositiveSmallIntegerField(verbose_name="Número")
    nombre  = models.CharField(max_length=200, verbose_name="Nombre de la Unidad")
    link    = models.URLField(max_length=500, blank=True, null=True, verbose_name="Link")

    class Meta:
        ordering        = ['libro__nombre', 'materia__nombre', 'numero']
        unique_together = ('libro', 'materia', 'numero')
        verbose_name        = "Unidad"
        verbose_name_plural = "Unidades"

    def __str__(self):
        return f"{self.libro.nombre} | {self.materia.nombre} | U.{self.numero}: {self.nombre}"


class Colegio(models.Model):
    """Institución educativa. Datos invariantes que no cambian entre años.

    Los datos que varían por año (valor_hora, activo) viven en ColegioAnio.
    """

    codigo       = models.CharField(max_length=50, blank=True, null=True,
                                    verbose_name="Código Interno")
    nombre       = models.CharField(max_length=200, unique=True,
                                    verbose_name="Nombre del Colegio")
    departamento = models.CharField(max_length=100, verbose_name="Departamento")
    ciudad       = models.CharField(max_length=100, verbose_name="Ciudad")
    direccion    = models.CharField(max_length=300, blank=True, null=True,
                                    verbose_name="Dirección")
    observacion  = models.TextField(blank=True, null=True, verbose_name="Observación")
    mapa_link    = models.URLField(blank=True, null=True, verbose_name="Link de Maps")

    class Meta:
        ordering            = ['nombre']
        verbose_name        = "Colegio"
        verbose_name_plural = "Colegios"

    def __str__(self):
        return self.nombre


class ColegioAnio(models.Model):
    """Instancia anual de un colegio. Representa al colegio en un año académico concreto.

    La separación Colegio / ColegioAnio permite:
    - Mantener datos históricos por año (clases, asignaciones, pagos).
    - Activar/desactivar un colegio para un año sin borrar su historial.
    - Definir un valor_hora distinto por año para la liquidación de pagos.

    Las propiedades proxy (nombre, ciudad, etc.) delegan al Colegio padre para
    que el resto del código pueda tratar a ColegioAnio como si fuera el colegio
    sin preocuparse de la doble tabla.
    """

    colegio = models.ForeignKey(
        Colegio, on_delete=models.CASCADE,
        related_name='anios', verbose_name="Colegio"
    )
    anio       = models.IntegerField(default=_anio_actual, verbose_name="Año")
    activo     = models.BooleanField(default=True, verbose_name="Activo")
    valor_hora = models.IntegerField(
        null=True, blank=True,
        verbose_name="Valor por Hora (COP)",
        help_text="Valor en pesos colombianos que se paga por hora de clase en este colegio/año",
    )

    class Meta:
        unique_together     = ('colegio', 'anio')
        ordering            = ['colegio__nombre', '-anio']
        verbose_name        = "Colegio-Año"
        verbose_name_plural = "Colegios-Año"

    # ── Propiedades proxy ──────────────────────────────────────
    # Los datos canónicos del colegio (nombre, ciudad, etc.) viven en Colegio.
    # Estas propiedades los exponen directamente en ColegioAnio para que los
    # templates y vistas no necesiten traversal explícito (.colegio.nombre).
    # IMPORTANTE: son read-only; los cambios deben hacerse sobre Colegio.

    @property
    def nombre(self):
        return self.colegio.nombre

    @property
    def codigo(self):
        return self.colegio.codigo

    @property
    def departamento(self):
        return self.colegio.departamento

    @property
    def ciudad(self):
        return self.colegio.ciudad

    @property
    def direccion(self):
        return self.colegio.direccion

    @property
    def observacion(self):
        return self.colegio.observacion

    @property
    def mapa_link(self):
        return self.colegio.mapa_link

    def __str__(self):
        return f"{self.colegio.nombre} ({self.anio})"


class Profesor(models.Model):
    """Docente de la empresa. Almacena datos personales, bancarios y de seguridad social.

    Diseño deliberado: todos los campos personales son opcionales (blank/null=True)
    porque los profesores se incorporan gradualmente y no siempre tienen todos los
    datos disponibles al momento del registro.

    ATENCIÓN — nombre_corto es una @property, NO un campo de BD:
    No se puede usar en .values(), .filter() ni .order_by(). Para listados que
    necesiten el nombre corto, traer nombre+apellido y calcular en Python.
    """

    class TipoCuenta(models.TextChoices):
        AHORROS   = 'Ahorros',   'Ahorros'
        CORRIENTE = 'Corriente', 'Corriente'

    class EstadoCivil(models.TextChoices):
        SOLTERO    = 'Soltero/a',    'Soltero/a'
        CASADO     = 'Casado/a',     'Casado/a'
        UNION      = 'Unión libre',  'Unión libre'
        DIVORCIADO = 'Divorciado/a', 'Divorciado/a'
        VIUDO      = 'Viudo/a',      'Viudo/a'

    class Banco(models.TextChoices):
        NEQUI       = 'Nequi',           'Nequi'
        BANCOLOMBIA = 'Bancolombia',     'Bancolombia'
        BOGOTA      = 'Banco de Bogotá', 'Banco de Bogotá'
        DAVIVIENDA  = 'Davivienda',      'Davivienda'
        DAVIPLATA   = 'Daviplata',       'Daviplata'
        NU          = 'Nu',              'Nu'
        BBVA        = 'BBVA',            'BBVA'

    nombre           = models.CharField(max_length=200, verbose_name="Nombre(s)")
    apellido         = models.CharField(max_length=200, blank=True, null=True,
                                        verbose_name="Apellido(s)")
    documento        = models.CharField(max_length=20, unique=True, blank=True, null=True,
                                        verbose_name="Cédula / Documento")
    fecha_nacimiento = models.DateField(blank=True, null=True,
                                        verbose_name="Fecha de Nacimiento")
    estado_civil     = models.CharField(max_length=20, blank=True, null=True,
                                        choices=EstadoCivil.choices, verbose_name="Estado Civil")
    talla_camisa     = models.CharField(max_length=10, blank=True, null=True,
                                        verbose_name="Talla Camisa")
    email            = models.EmailField(blank=True, null=True,
                                         verbose_name="Correo Electrónico")
    celular          = models.CharField(max_length=20, blank=True, null=True,
                                        verbose_name="Celular")
    departamento     = models.CharField(max_length=100, blank=True, null=True,
                                        verbose_name="Departamento")
    ciudad           = models.CharField(max_length=100, blank=True, null=True,
                                        verbose_name="Ciudad")
    direccion        = models.CharField(max_length=300, blank=True, null=True,
                                        verbose_name="Dirección")
    materias         = models.ManyToManyField(
                            Materia, blank=True,
                            related_name='profesores',
                            verbose_name="Materias que dicta"
                        )
    disponibilidad   = models.CharField(max_length=200, blank=True, null=True,
                                        verbose_name="Disponibilidad")

    # Choices colombianos de seguridad social — se mantienen aquí para evitar
    # una tabla separada: el catálogo es estático y raramente cambia.
    class Eps(models.TextChoices):
        NUEVA_EPS    = 'Nueva EPS',    'Nueva EPS'
        SURA         = 'Sura',         'Sura'
        SANITAS      = 'Sanitas',      'Sanitas'
        SALUD_TOTAL  = 'Salud Total',  'Salud Total'
        COMPENSAR    = 'Compensar',    'Compensar'
        COOSALUD     = 'Coosalud',     'Coosalud'
        FAMISANAR    = 'Famisanar',    'Famisanar'
        MUTUAL_SER   = 'Mutual Ser',   'Mutual Ser'
        ALIANSALUD   = 'Aliansalud',   'Aliansalud'
        COMFENALCO   = 'Comfenalco',   'Comfenalco'
        COOMEVA      = 'Coomeva',      'Coomeva'
        OTRA         = 'Otra',         'Otra'

    class FondoPension(models.TextChoices):
        PORVENIR     = 'Porvenir',     'Porvenir'
        PROTECCION   = 'Protección',   'Protección'
        COLFONDOS    = 'Colfondos',    'Colfondos'
        OLD_MUTUAL   = 'Old Mutual',   'Old Mutual'
        COLPENSIONES = 'Colpensiones', 'Colpensiones'
        OTRO         = 'Otro',         'Otro'

    eps              = models.CharField(max_length=100, blank=True, null=True,
                                        choices=Eps.choices, verbose_name="EPS")
    fondo_pension    = models.CharField(max_length=100, blank=True, null=True,
                                        choices=FondoPension.choices,
                                        verbose_name="Fondo de Pensión")
    banco            = models.CharField(max_length=100, blank=True, null=True,
                                        choices=Banco.choices, verbose_name="Banco")
    tipo_cuenta      = models.CharField(max_length=20, blank=True, null=True,
                                        choices=TipoCuenta.choices, verbose_name="Tipo de Cuenta")
    cuenta_bancaria  = models.CharField(max_length=50, blank=True, null=True,
                                        verbose_name="Cuenta Bancaria")
    activo           = models.BooleanField(default=True, verbose_name="Activo")

    @property
    def nombre_corto(self):
        """Primer nombre + primer apellido. Solo para display, no existe en BD.

        NUNCA usar en queryset lookups (.filter, .values, .order_by).
        Para listas masivas, calcular con: f"{nombre.split()[0]} {apellido.split()[0]}".
        """
        primer_nombre   = self.nombre.split()[0] if self.nombre else ''
        primer_apellido = self.apellido.split()[0] if self.apellido else ''
        return f"{primer_nombre} {primer_apellido}".strip()

    def __str__(self):
        return self.nombre_corto