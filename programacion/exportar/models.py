from django.db import models
from django.contrib.auth.models import User
from configuracion.models import Profesor, ColegioAnio


class PagoRealizado(models.Model):
    """Registro inmutable de un pago liquidado a un profesor por un día de clases.

    El constraint único (profesor, colegio, fecha) garantiza que la misma clase
    no se marque como pagada dos veces. El endpoint ajax_marcar_pago usa
    get_or_create para respetar este constraint sin lanzar excepción.

    El campo 'valor' se calcula en la vista como horas × ColegioAnio.valor_hora
    y se guarda desnormalizado para preservar el valor histórico aunque cambie
    la tarifa del colegio en el futuro.
    """

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
    valor       = models.IntegerField(verbose_name='Valor pagado (COP)')
    fecha_pago  = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de pago')
    marcado_por = models.ForeignKey(
        # SET_NULL permite que el registro sobreviva si se elimina el usuario admin.
        User, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='pagos_marcados', verbose_name='Marcado por',
    )

    class Meta:
        unique_together     = ('profesor', 'colegio', 'fecha')
        ordering            = ['-fecha', 'profesor__nombre']
        verbose_name        = 'Pago Realizado'
        verbose_name_plural = 'Pagos Realizados'

    def __str__(self):
        return f"{self.profesor} | {self.colegio} | {self.fecha} | ${self.valor:,}"
