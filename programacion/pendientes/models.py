from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Tarea(models.Model):
    """
    Tarea del tablero Kanban visible en la página de inicio.

    El ciclo de vida es: pendiente → gestion → completado.
    Las tareas completadas no se borran — se ocultan en la UI después de 2 días
    para mantener el historial. La fecha_completado se gestiona automáticamente
    en save() para garantizar consistencia sin depender del caller.
    """

    ESTADOS = [
        ('pendiente',  'Pendiente'),
        ('gestion',    'En Gestión'),
        ('completado', 'Completado'),
    ]

    titulo          = models.CharField(max_length=200, verbose_name="Título")
    descripcion     = models.TextField(blank=True, null=True, verbose_name="Descripción")
    estado          = models.CharField(max_length=20, choices=ESTADOS, default='pendiente')
    creado_por      = models.ForeignKey(User, on_delete=models.CASCADE)
    # SET_NULL porque conservar la tarea aunque el usuario que la completó sea eliminado
    completado_por  = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='tareas_completadas'
    )
    fecha_creacion   = models.DateTimeField(auto_now_add=True)
    # Null mientras la tarea no esté completada; se auto-rellena en save()
    fecha_completado = models.DateTimeField(blank=True, null=True)

    def save(self, *args, **kwargs):
        # Sincronizar fecha_completado con el estado para mantener consistencia.
        # No se delega al caller porque un update() directo saltaría esta lógica;
        # la vista cambiar_estado usa .save() precisamente para que esto se ejecute.
        if self.estado == 'completado' and not self.fecha_completado:
            self.fecha_completado = timezone.now()
        elif self.estado != 'completado':
            # Si la tarea retrocede de completado, limpiar la fecha para no mostrar
            # una fecha de completado desactualizada en un futuro re-completado.
            self.fecha_completado = None
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'prog_tareas'
        ordering = ['-fecha_creacion']
