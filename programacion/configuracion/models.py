import os
import re
from django.contrib.auth.models import User
from django.db import models
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from datetime import date


def _anio_actual():
    """Valor por defecto callable para ColegioAnio.anio — evita que el año quede
    hardcodeado en la migración y siempre toma el año de ejecución."""
    return date.today().year


def periodo_por_defecto(calendario, anio):
    """Ventana (fecha_inicio, fecha_fin) por defecto de un periodo según su calendario.

    - Calendario A (año natural): 1-ene a 31-dic de `anio`.
    - Calendario B (hemisferio norte): 1-ago de `anio` a 30-jun de `anio+1`. El periodo
      cruza dos años calendario; `anio` es el año de inicio (ancla del ColegioAnio).

    Centralizado aquí para que vistas, formularios y la clonación de año calculen el
    rango de la misma forma. El parámetro es el string del choice ('A'/'B'), no el
    Colegio, para poder llamarlo desde migraciones sin instanciar el modelo.
    """
    if calendario == Colegio.Calendario.B:
        return date(anio, 8, 1), date(anio + 1, 6, 30)
    return date(anio, 1, 1), date(anio, 12, 31)


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
        db_table            = 'prog_materias'
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
        db_table            = 'prog_libros'
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
        db_table        = 'prog_unidades'
        ordering        = ['libro__nombre', 'materia__nombre', 'numero']
        unique_together = ('libro', 'materia', 'numero')
        verbose_name        = "Unidad"
        verbose_name_plural = "Unidades"

    def __str__(self):
        return f"{self.libro.nombre} | {self.materia.nombre} | U.{self.numero}: {self.nombre}"


class Colegio(models.Model):
    """Institución educativa. Datos invariantes que no cambian entre años.

    Los datos que varían por año (valor_hora, activo) viven en ColegioAnio.

    El `calendario` (A/B) define cómo se delimita el periodo académico de cada
    ColegioAnio: A = año natural (ene–dic); B = ago→jun del año siguiente. Es una
    propiedad de la institución, no del año, por eso vive aquí y no en ColegioAnio.
    """

    class Calendario(models.TextChoices):
        A = 'A', 'Calendario A (año natural: ene–dic)'
        B = 'B', 'Calendario B (ago–jun del año siguiente)'

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
    calendario   = models.CharField(max_length=1, choices=Calendario.choices,
                                    default=Calendario.A, verbose_name="Calendario")

    class Meta:
        db_table            = 'prog_colegios'
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
    # Ventana real del periodo académico. Se autocalcula en save() según el calendario
    # del Colegio (ver periodo_por_defecto); editable para ajustes finos por colegio.
    # null=True para permitir el backfill por migración y que save() las complete.
    fecha_inicio = models.DateField(null=True, blank=True, verbose_name="Inicio del periodo")
    fecha_fin    = models.DateField(null=True, blank=True, verbose_name="Fin del periodo")

    class Meta:
        db_table            = 'prog_colegio_anios'
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

    @property
    def calendario(self):
        return self.colegio.calendario

    @property
    def periodo_label(self):
        """Etiqueta del periodo para selectores y títulos.

        A → "2025"; B → "2025-2026" (rango cruzado, inequívoco frente a un A 2025)."""
        if self.colegio.calendario == Colegio.Calendario.B:
            return f"{self.anio}-{self.anio + 1}"
        return str(self.anio)

    @property
    def rango(self):
        """Ventana (inicio, fin) efectiva del periodo.

        Usa las fechas guardadas; si faltan (registro a medio migrar), las calcula
        desde el calendario. Fuente única para validar clases, construir la matriz y
        fijar defaults de asignaciones."""
        if self.fecha_inicio and self.fecha_fin:
            return self.fecha_inicio, self.fecha_fin
        return periodo_por_defecto(self.colegio.calendario, self.anio)

    def save(self, *args, **kwargs):
        # Completar la ventana del periodo cuando no se suministra (espejo de
        # Asignacion.save()). Requiere el colegio para conocer el calendario.
        if (not self.fecha_inicio or not self.fecha_fin) and self.colegio_id:
            inicio, fin = periodo_por_defecto(self.colegio.calendario, self.anio)
            if not self.fecha_inicio:
                self.fecha_inicio = inicio
            if not self.fecha_fin:
                self.fecha_fin = fin
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.colegio.nombre} ({self.periodo_label})"


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

    class Meta:
        db_table = 'prog_profesores'

    @staticmethod
    def nombre_corto_de(nombre, apellido):
        """Primer nombre + primer apellido a partir de strings sueltos.

        Misma regla que la property nombre_corto, para listados masivos que
        traen nombre/apellido vía .values()/.values_list() sin instanciar el
        modelo (acepta None/'' en cualquiera de los dos).
        """
        primer_nombre   = nombre.split()[0] if nombre else ''
        primer_apellido = apellido.split()[0] if apellido else ''
        return f"{primer_nombre} {primer_apellido}".strip()

    @property
    def nombre_corto(self):
        """Primer nombre + primer apellido. Solo para display, no existe en BD.

        NUNCA usar en queryset lookups (.filter, .values, .order_by).
        Para listas masivas, usar Profesor.nombre_corto_de(nombre, apellido).
        """
        return self.nombre_corto_de(self.nombre, self.apellido)

    def __str__(self):
        return self.nombre_corto


def _documento_profesor_upload_to(instance, filename):
    """Ruta/nombre limpio del documento: ``profesores/<slug-profesor>/<slug-archivo><ext>``.

    Agrupa los archivos por profesor en una carpeta legible y conserva el nombre
    original (slugificado) para distinguir CV / cédula / RUT de un vistazo. Con
    ``FileSystemStorage`` (dev) o S3 (prod) las colisiones reciben un sufijo único
    automático, así que subir dos archivos con el mismo nombre no se pisa.
    """
    prof = instance.profesor
    slug_prof = slugify(prof.nombre_corto) or str(prof.pk or 'profesor')
    base = slugify(os.path.splitext(filename)[0]) or 'documento'
    ext = os.path.splitext(filename)[1].lower()
    return f'profesores/{slug_prof}/{base}{ext}'


class DocumentoProfesor(models.Model):
    """Archivo adjunto a la ficha de un profesor (CV, cédula, RUT, etc.).

    Sin límite de cantidad: varios documentos por profesor, con historial de quién
    subió qué y cuándo. Mismo patrón de almacenamiento que los soportes de pago
    (``FileField`` sobre ``STORAGES['default']`` → disco en dev, Supabase en prod) y
    descarga **proxiada** por una vista protegida, nunca por URL pública. La
    validación (extensión/tamaño) vive en ``configuracion.documentos``.
    """

    profesor = models.ForeignKey(Profesor, on_delete=models.CASCADE,
                                 related_name='documentos')
    archivo = models.FileField(upload_to=_documento_profesor_upload_to)
    nombre_original = models.CharField(max_length=255, blank=True)
    subido_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='documentos_profesor')
    subido_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'prog_profesores_documentos'
        ordering = ['-subido_en']
        verbose_name = 'Documento de profesor'
        verbose_name_plural = 'Documentos de profesor'

    def __str__(self):
        return f'{self.nombre_original or self.archivo.name} ({self.profesor})'