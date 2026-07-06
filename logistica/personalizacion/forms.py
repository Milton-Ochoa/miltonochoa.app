"""Forms de personalización.

Fase 2 (CRUD): `PlantillaForm` — subida de una plantilla PDF (nombre + tipo +
archivo). La validación DURA del archivo (solo `.pdf`, ≤10 MB) la hace la vista
con `validaciones.validar_plantilla_pdf` antes de guardar, no el form: así el
mensaje de error sale por `messages` (toast) con el mismo patrón que los
adjuntos de inventario.
"""
from django import forms

from .models import PlantillaPersonalizacion


class _BootstrapMixin:
    """Aplica las clases Bootstrap a todos los widgets de una vez."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            widget = campo.widget
            if isinstance(widget, forms.Select):
                widget.attrs.setdefault('class', 'form-select')
            else:
                widget.attrs.setdefault('class', 'form-control')


class PlantillaForm(_BootstrapMixin, forms.ModelForm):
    class Meta:
        model = PlantillaPersonalizacion
        fields = ['nombre', 'tipo', 'archivo']
        widgets = {
            'archivo': forms.ClearableFileInput(attrs={'accept': '.pdf'}),
        }
