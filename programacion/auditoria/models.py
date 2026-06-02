from django.db import models
from django.contrib.auth.models import User
from programacion.configuracion.models import ColegioAnio, Profesor


class AlertaAuditoria(models.Model):
    """
    Registra un error de programación detectado por el motor de auditoría.

    Ciclo de vida de una alerta:
      1. Se crea con vigente=True cuando el motor la detecta por primera vez.
      2. Si el error desaparece de los datos (ej. se corrigió la clase), el motor
         la marca vigente=False y registra resuelto_en automáticamente.
      3. Si un administrador decide ignorarla manualmente, también queda vigente=False
         pero además se registra ignorado_por y motivo_ignorado.
      4. Si el error reaparece después de haber sido resuelto, el motor la reactiva
         (vigente=True, resuelto_en=None) en lugar de crear un duplicado.

    Deduplicación mediante `huella`:
      El campo `huella` es un hash MD5 de los componentes que identifican el error
      (tipo + colegio + grado + materia + unidad/fecha). Permite insertar o ignorar
      alertas sin hacer queries complejas por múltiples campos.

    Colegios implicados:
      Para alertas de tipo CONFLICTO el error afecta a varios colegios (el profesor
      tiene clases en todos ellos el mismo día). El FK `colegio` se deja nulo en ese
      caso y los colegios se almacenan en la M2M `colegios_implicados`.
    """

    class Tipo(models.TextChoices):
        DUPLICADO  = 'duplicado',  'Unidad Duplicada'
        CONFLICTO  = 'conflicto',  'Choque de Profesor'
        SECUENCIA  = 'secuencia',  'Salto de Secuencia'

    tipo        = models.CharField(max_length=20, choices=Tipo.choices)
    huella      = models.CharField(
        max_length=255, unique=True,
        help_text='Hash MD5 determinista que identifica este error concreto. '
                  'Permite deduplicar sin buscar por múltiples campos.',
    )
    mensaje     = models.TextField()

    # Para DUPLICADO y SECUENCIA: el colegio donde ocurre el error.
    # Para CONFLICTO: nulo — usar colegios_implicados.
    colegio     = models.ForeignKey(
        ColegioAnio, on_delete=models.CASCADE, related_name='alertas',
        null=True, blank=True,
    )
    # Poblado solo en alertas de tipo CONFLICTO.
    profesor    = models.ForeignKey(
        Profesor, on_delete=models.CASCADE, related_name='alertas',
        null=True, blank=True,
    )
    # Solo para CONFLICTO: lista de todos los colegios involucrados en el choque.
    colegios_implicados = models.ManyToManyField(
        ColegioAnio, blank=True, related_name='alertas_implicado',
        help_text='Para conflictos de profesor que involucran varios colegios.',
    )

    vigente          = models.BooleanField(default=True, db_index=True)
    detectado        = models.DateTimeField(auto_now_add=True)
    # Fecha en que dejó de estar vigente, ya sea por corrección automática o ignorado manual.
    resuelto_en      = models.DateTimeField(null=True, blank=True)
    # Presente solo cuando un admin ignoró la alerta manualmente (no cuando se resolvió sola).
    motivo_ignorado  = models.TextField(null=True, blank=True, verbose_name='Motivo para ignorar')
    ignorado_por     = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='alertas_ignoradas', verbose_name='Ignorado por',
    )

    class Meta:
        db_table = 'prog_alertas_auditoria'
        ordering = ['-detectado']
        verbose_name = 'Alerta de Auditoría'
        verbose_name_plural = 'Alertas de Auditoría'
        indexes = [
            # Índice compuesto para el filtro más común: alertas vigentes de un colegio.
            models.Index(fields=['colegio', 'vigente']),
            models.Index(fields=['tipo']),
        ]

    def __str__(self):
        return f'[{self.get_tipo_display()}] {self.mensaje[:80]}'
