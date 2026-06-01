from django.db import models
from django.contrib.auth.models import User as _User
from django.core.exceptions import ValidationError
from configuracion.models import Colegio, ColegioAnio, Profesor, NombreLibro, Materia
from datetime import date


# ─────────────────────────────────────────────────────────────
# GRADO
# ─────────────────────────────────────────────────────────────

class Grado(models.Model):
    """
    Catálogo global de grados escolares, compartido entre todos los colegios y años.

    Diseño intencionado: un solo registro por nombre (unique=True) evita
    duplicados por variaciones de espaciado o mayúsculas. Siempre usar
    get_or_create en el backend; nunca aceptar texto libre sin normalizar.
    """
    nombre = models.CharField(
        max_length=50, unique=True, verbose_name="Nombre del Grado"
    )

    class Meta:
        ordering            = ['nombre']
        verbose_name        = "Grado"
        verbose_name_plural = "Grados"

    def __str__(self):
        return self.nombre


# ─────────────────────────────────────────────────────────────
# BLOQUE
# ─────────────────────────────────────────────────────────────

class Bloque(models.Model):
    """
    Franja horaria recurrente de un grado dentro de un ColegioAnio.

    Un bloque representa el "cuándo" de las clases: qué grado, a qué hora.
    Las instancias concretas de clase se registran en el modelo Clase,
    referenciando al bloque como ancla de horario.
    """
    colegio     = models.ForeignKey(ColegioAnio, on_delete=models.CASCADE,
                                    related_name='bloques')
    grado       = models.ForeignKey(Grado, on_delete=models.PROTECT,
                                    verbose_name="Grado")
    hora_inicio = models.TimeField(verbose_name="Hora de Inicio")
    hora_fin    = models.TimeField(verbose_name="Hora de Fin")

    class Meta:
        ordering = ['grado__nombre', 'hora_inicio']
        indexes = [
            models.Index(fields=['colegio', 'grado']),
        ]

    @property
    def hora(self):
        """Rango horario en formato 12h AM/PM para mostrar en UI y exportaciones."""
        if self.hora_inicio and self.hora_fin:
            def _fmt(t):
                h = t.hour % 12 or 12
                m = t.strftime('%M')
                periodo = 'AM' if t.hour < 12 else 'PM'
                return f"{h}:{m} {periodo}"
            return f"{_fmt(self.hora_inicio)} - {_fmt(self.hora_fin)}"
        return ''

    @property
    def duracion_minutos(self):
        """Duración de la sesión en minutos. Usado para calcular horas en liquidación de pagos."""
        if self.hora_inicio and self.hora_fin:
            inicio = self.hora_inicio.hour * 60 + self.hora_inicio.minute
            fin    = self.hora_fin.hour * 60 + self.hora_fin.minute
            return max(0, fin - inicio)
        return 0

    def __str__(self):
        return f"{self.grado.nombre} | {self.hora}"


# ─────────────────────────────────────────────────────────────
# ASIGNACION DE LIBRO
# ─────────────────────────────────────────────────────────────

class Asignacion(models.Model):
    """
    Qué libro utiliza un grado durante un período de tiempo en un colegio.

    El campo `libro` es nullable a propósito: un grado puede aparecer en el
    panel de configuración sin tener libro asignado aún (se muestra badge
    "Sin libro" en la UI). Nunca asumir que libro != None.

    Las fechas se usan para determinar qué unidades son válidas en un día
    concreto, permitiendo que un grado cambie de libro a mitad de año.
    Si no se suministran fechas al guardar, el método save() las infiere
    como el 1 de enero y 31 de diciembre del año del ColegioAnio.
    """
    colegio      = models.ForeignKey(ColegioAnio, on_delete=models.CASCADE,
                                     related_name='asignaciones')
    grado        = models.ForeignKey(Grado, on_delete=models.PROTECT,
                                     verbose_name="Grado")
    libro        = models.ForeignKey(NombreLibro, on_delete=models.PROTECT,
                                     null=True, blank=True,
                                     verbose_name="Libro")
    fecha_inicio = models.DateField(null=True, blank=True,
                                    verbose_name="Fecha de Inicio")
    fecha_fin    = models.DateField(null=True, blank=True,
                                    verbose_name="Fecha de Fin")

    class Meta:
        verbose_name        = "Asignación de Libro"
        verbose_name_plural = "Asignaciones de Libros"
        indexes = [
            models.Index(fields=['colegio', 'grado', 'fecha_inicio', 'fecha_fin']),
        ]

    def save(self, *args, **kwargs):
        # Garantizar que siempre haya un rango de fechas válido.
        # Usar el año del colegio evita asignaciones que se desborden al año siguiente.
        if not self.fecha_inicio or not self.fecha_fin:
            anio = self.colegio.anio if self.colegio_id else date.today().year
            if not self.fecha_inicio:
                self.fecha_inicio = date(anio, 1, 1)
            if not self.fecha_fin:
                self.fecha_fin = date(anio, 12, 31)
        super().save(*args, **kwargs)

    def __str__(self):
        libro_str = self.libro.nombre if self.libro_id else "Sin libro"
        return f"{self.colegio.nombre} - {self.grado.nombre} - {libro_str}"


# ─────────────────────────────────────────────────────────────
# CLASE
# ─────────────────────────────────────────────────────────────

class Clase(models.Model):
    """
    Registro de una clase concreta en una fecha y bloque determinados.

    Convención del campo `unidad` (crítico para toda la lógica de estadísticas):
      - "1", "2", ... → unidad normal del libro asignado al grado
      - "S"           → socialización de simulacro (excluida de estadísticas)
      - número + libro_especial != null → Material Asignado (libro fuera del currículo)

    Las clases con es_evento=True o cancelada=True se excluyen de los cálculos
    de avance y de las propuestas de recálculo de secuencia.

    El campo enlace_personalizado solo se persiste en materiales especiales y
    socializaciones; para clases normales el enlace viene de Unidad.link.
    """
    colegio       = models.ForeignKey(ColegioAnio, on_delete=models.CASCADE)
    bloque        = models.ForeignKey(Bloque, on_delete=models.CASCADE)
    fecha         = models.DateField()
    profesor      = models.ForeignKey(Profesor, on_delete=models.SET_NULL,
                                      null=True, blank=True)
    materia       = models.ForeignKey(Materia, on_delete=models.SET_NULL,
                                      null=True, blank=True)
    # Ver convención de valores en el docstring de la clase
    unidad              = models.CharField(max_length=50, blank=True, null=True)
    # Solo se rellena cuando es un Material Asignado (libro con es_material_asignado=True)
    libro_especial      = models.ForeignKey(
                              NombreLibro, on_delete=models.SET_NULL,
                              null=True, blank=True, related_name='clases_especiales',
                              verbose_name="Libro Especial")
    # Solo persiste para materiales especiales y socializaciones;
    # en clases normales se resuelve desde Unidad.link en tiempo de consulta
    enlace_personalizado = models.URLField(max_length=500, blank=True, null=True,
                                           verbose_name="Enlace Personalizado")
    es_evento     = models.BooleanField(default=False,
                                        verbose_name="¿Es un evento especial?")
    titulo_evento = models.CharField(max_length=200, blank=True, null=True,
                                     verbose_name="Título del Evento")
    cancelada     = models.BooleanField(default=False,
                                        verbose_name="¿Clase Cancelada?")
    comentarios   = models.TextField(blank=True, null=True,
                                     verbose_name="Comentarios / Motivo")

    class Meta:
        # Un bloque solo puede tener una clase por fecha
        unique_together = ('fecha', 'bloque')
        indexes = [
            # Consultas de dashboard y matriz (filtro principal por colegio+fecha)
            models.Index(fields=['colegio', 'fecha']),
            # Auditoría: buscar clases canceladas en un rango
            models.Index(fields=['fecha', 'cancelada']),
            # Vista de horario del profesor
            models.Index(fields=['profesor', 'fecha']),
            # Batch-load de unidades para libros especiales en _construir_matriz
            models.Index(fields=['libro_especial']),
            # Lookups de celda por bloque y fecha en dashboard
            models.Index(fields=['bloque', 'fecha']),
        ]

    def clean(self):
        super().clean()
        # Prevenir inconsistencias de datos: el bloque debe pertenecer al mismo colegio.
        # En producción esto se garantiza también en la UI, pero validamos aquí como
        # segunda línea de defensa.
        if self.bloque_id and self.colegio_id:
            if self.bloque.colegio_id != self.colegio_id:
                raise ValidationError(
                    'El bloque debe pertenecer al mismo colegio que la clase.'
                )
        if self.fecha and self.colegio_id:
            if self.fecha.year != self.colegio.anio:
                raise ValidationError(
                    f'La fecha debe pertenecer al año {self.colegio.anio} del colegio.'
                )

    def __str__(self):
        return f"{self.fecha} | {self.bloque}"


# ─────────────────────────────────────────────────────────────
# CLASE PARTICULAR
# ─────────────────────────────────────────────────────────────

class ClaseParticular(models.Model):
    """
    Clase particular que dicta un profesor fuera del horario de colegios.

    El campo `ciudad` es texto libre intencionalmente: puede contener una ciudad
    o una dirección completa. No es FK ni choices, para permitir flexibilidad
    de ubicación sin restricciones de catálogo.
    """
    profesor    = models.ForeignKey(Profesor, on_delete=models.CASCADE,
                                    verbose_name="Profesor")
    estudiante  = models.CharField(max_length=200,
                                   verbose_name="Nombre del Estudiante (Colegio)")
    # Texto libre: puede ser ciudad o dirección exacta
    ciudad      = models.CharField(max_length=100, default="Bucaramanga",
                                   verbose_name="Ciudad")
    mapa_link   = models.URLField(blank=True, null=True, verbose_name="Link de Maps")
    fecha       = models.DateField(verbose_name="Fecha de la Clase")
    hora_inicio = models.TimeField(verbose_name="Hora de Inicio")
    hora_fin    = models.TimeField(verbose_name="Hora de Fin")
    grado       = models.ForeignKey(Grado, on_delete=models.PROTECT,
                                    verbose_name="Grado")
    material    = models.CharField(max_length=200, verbose_name="Libro / Material")
    materia     = models.ForeignKey(Materia, on_delete=models.PROTECT,
                                    verbose_name="Asignatura")
    unidad      = models.CharField(max_length=50, verbose_name="Unidad")

    class Meta:
        verbose_name        = "Clase Particular"
        verbose_name_plural = "Clases Particulares"

    @property
    def hora(self):
        """Rango horario en formato 12h AM/PM. Misma lógica que Bloque.hora."""
        if self.hora_inicio and self.hora_fin:
            def _fmt(t):
                h = t.hour % 12 or 12
                periodo = 'AM' if t.hour < 12 else 'PM'
                return f"{h}:{t.strftime('%M')} {periodo}"
            return f"{_fmt(self.hora_inicio)} - {_fmt(self.hora_fin)}"
        return ''

    def __str__(self):
        return f"Particular: {self.estudiante} - {self.profesor.nombre} ({self.fecha})"


# ─────────────────────────────────────────────────────────────
# HISTORIAL DE CAMBIOS
# ─────────────────────────────────────────────────────────────

class HistorialCambio(models.Model):
    """
    Registro de auditoría de operaciones create/edit/delete sobre objetos del sistema.

    No es un log de acceso general — solo se registran cambios explícitos a
    Clases, Bloques y Asignaciones mediante llamadas a historial.registrar_cambio().

    El campo `objeto_str` guarda el __str__ del objeto en el momento del cambio;
    preserva información legible incluso si el objeto es eliminado después.
    El campo `detalle` es JSON libre para contexto adicional por tipo de cambio.
    """
    TIPO_CREAR    = 'crear'
    TIPO_EDITAR   = 'editar'
    TIPO_ELIMINAR = 'eliminar'
    TIPO_CHOICES  = [
        (TIPO_CREAR,    'Creado'),
        (TIPO_EDITAR,   'Editado'),
        (TIPO_ELIMINAR, 'Eliminado'),
    ]

    objeto_tipo = models.CharField(max_length=50)
    objeto_id   = models.BigIntegerField()
    # Snapshot del __str__ al momento del cambio; útil si el objeto luego se borra
    objeto_str  = models.CharField(max_length=300)
    colegio     = models.ForeignKey(
        ColegioAnio, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='historial'
    )
    tipo        = models.CharField(max_length=10, choices=TIPO_CHOICES)
    usuario     = models.ForeignKey(
        _User, on_delete=models.SET_NULL, null=True, blank=True
    )
    fecha       = models.DateTimeField(auto_now_add=True)
    detalle     = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-fecha']
        indexes = [
            # Para buscar el historial de un objeto específico (ej: quién editó esta clase)
            models.Index(fields=['objeto_tipo', 'objeto_id']),
            # Para filtrar historial por colegio y rango de fechas
            models.Index(fields=['colegio', 'fecha']),
            # Para filtrar historial por usuario (historial_global con filtro usuario)
            models.Index(fields=['usuario', 'fecha']),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.objeto_tipo} {self.objeto_id} — {self.fecha:%d/%m/%Y %H:%M}"