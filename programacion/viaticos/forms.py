from django import forms

from programacion.configuracion.models import Colegio, Profesor
from .models import SolicitudViatico


class SolicitudViaticoForm(forms.ModelForm):
    """Datos de identidad/fechas/observaciones de una solicitud de viáticos.

    Solo cubre los campos *fijos* del formulario. Los gastos (parte variable) y
    el snapshot bloqueado NO viven aquí: los gastos los procesa la vista desde
    `request.POST.getlist(...)` y el snapshot lo copia el servidor desde las FK
    (ver `SolicitudViatico.aplicar_snapshot`). Los selects de profesor/colegio
    se renderizan a mano en la plantilla (con `data-*` para el autorrelleno),
    pero siguen ligados a estos campos para que la validación del ModelForm
    valide la FK enviada.
    """

    class Meta:
        model  = SolicitudViatico
        fields = ['profesor', 'colegio', 'fecha_viaje', 'fecha_regreso', 'observaciones']
        widgets = {
            'profesor':      forms.Select(attrs={'class': 'form-select'}),
            'colegio':       forms.Select(attrs={'class': 'form-select'}),
            # format='%Y-%m-%d' es obligatorio: <input type="date"> solo muestra valores
            # en ISO; sin él Django renderiza la fecha localizada (dd/mm/aaaa) y el
            # navegador la descarta → el campo aparece vacío al editar.
            'fecha_viaje':   forms.DateInput(attrs={'class': 'form-control', 'type': 'date'},
                                             format='%Y-%m-%d'),
            'fecha_regreso': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'},
                                             format='%Y-%m-%d'),
            'observaciones': forms.Textarea(attrs={'class': 'form-control', 'rows': 3,
                                                   'placeholder': 'Observaciones (opcional)...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['profesor'].queryset = Profesor.objects.order_by('nombre', 'apellido')
        self.fields['colegio'].queryset  = Colegio.objects.order_by('nombre')

    def clean(self):
        cleaned = super().clean()
        viaje, regreso = cleaned.get('fecha_viaje'), cleaned.get('fecha_regreso')
        if viaje and regreso and regreso < viaje:
            self.add_error('fecha_regreso',
                           'La fecha de regreso no puede ser anterior a la de viaje.')
        return cleaned
