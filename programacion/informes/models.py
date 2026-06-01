from django.db import models
from programacion.configuracion.models import Profesor
from programacion.colegios.models import Clase, ClaseParticular


class Informe(models.Model):
    """
    Informe de sesión vinculado a exactamente UNA clase (regular o particular).

    El constraint de base de datos garantiza la exclusividad a nivel de motor,
    no solo a nivel de aplicación — impide estados imposibles aunque la app falle.
    Los campos de cabecera (colegio_nombre, grado, etc.) se desnormalizan al crear
    para que el informe sea legible aunque la clase original sea eliminada.
    """

    # FK a Clase o ClaseParticular: exactamente una debe ser no nula.
    # La relación OneToOne impide dos informes para la misma clase.
    profesor         = models.ForeignKey(Profesor, on_delete=models.CASCADE, related_name='informes')
    clase            = models.OneToOneField(Clase, on_delete=models.CASCADE,
                                            null=True, blank=True, related_name='informe')
    clase_particular = models.OneToOneField(ClaseParticular, on_delete=models.CASCADE,
                                            null=True, blank=True, related_name='informe')

    # Datos de cabecera copiados en el momento de creación.
    # Se guardan como texto para sobrevivir reorganizaciones del catálogo.
    colegio_nombre   = models.CharField(max_length=200)
    grado            = models.CharField(max_length=50)
    fecha            = models.DateField()
    materia          = models.CharField(max_length=100)
    tematica         = models.CharField(max_length=200)   # Nombre de la unidad impartida
    material         = models.CharField(max_length=200)   # Libro o recurso utilizado

    # Sección pedagógica: completada por el profesor después de la clase.
    # Todos blank=True porque el informe puede guardarse como borrador.
    actividades      = models.TextField(blank=True, default='')
    fortalezas       = models.TextField(blank=True, default='')
    debilidades      = models.TextField(blank=True, default='')
    recomendaciones  = models.TextField(blank=True, default='')
    bibliografia     = models.TextField(blank=True, default='')

    # Auditoría de creación/modificación (auto-gestionados por Django)
    creado_en        = models.DateTimeField(auto_now_add=True)
    actualizado_en   = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'Informe de Sesión'
        verbose_name_plural = 'Informes de Sesión'
        ordering            = ['-fecha', 'colegio_nombre']
        constraints = [
            # Garantía a nivel de BD: un informe pertenece a Clase XOR ClaseParticular.
            # Sin este constraint, un bug en la vista podría crear informes huérfanos
            # o doblemente vinculados que serían silenciosamente ignorados.
            models.CheckConstraint(
                check=(
                    models.Q(clase__isnull=False, clase_particular__isnull=True) |
                    models.Q(clase__isnull=True, clase_particular__isnull=False)
                ),
                name='informe_exactamente_una_clase',
            ),
        ]

    def __str__(self):
        return f"{self.fecha} | {self.profesor} | {self.colegio_nombre} {self.grado}"

    @property
    def completado(self):
        """
        True si el profesor ya llenó el campo Actividades.

        Se usa 'actividades' como señal de completitud porque es el campo
        más representativo del contenido pedagógico. No existe en BD —
        no usar en .values() ni en filtros ORM.
        """
        return bool(self.actividades.strip())
