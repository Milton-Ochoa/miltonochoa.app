"""Forms de personalización.

Fase 2 (CRUD): `PlantillaForm` — subida de una plantilla PDF (nombre + tipo +
archivo). La validación DURA del archivo (solo `.pdf`, ≤10 MB) la hace la vista
con `validaciones.validar_plantilla_pdf` antes de guardar, no el form: así el
mensaje de error sale por `messages` (toast) con el mismo patrón que los
adjuntos de inventario.

Fase 3 (generación): `GenerarForm` — elige plantilla + colegio (+ número de
prueba si es PENSAR) + Excel de estudiantes. El tipo se deriva de la plantilla;
el `<select>` marca cada opción con `data-tipo` (widget `PlantillaSelect`) para
que el JS muestre/oculte el número de prueba.
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


class PlantillaSelect(forms.Select):
    """`<select>` de plantillas que añade `data-tipo` a cada opción, para que el
    JS de `generar.html` muestre el número de prueba solo cuando el tipo es
    PENSAR (sin un roundtrip al servidor)."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        # `value` es un ModelChoiceIteratorValue con la instancia detrás; la
        # opción vacía ("— Selecciona —") no la tiene.
        if value:
            option['attrs']['data-tipo'] = value.instance.tipo
        return option


class GenerarForm(_BootstrapMixin, forms.Form):
    """Datos de una generación (nada se persiste): plantilla + colegio + número
    de prueba (solo PENSAR) + Excel de estudiantes."""

    plantilla = forms.ModelChoiceField(
        queryset=PlantillaPersonalizacion.objects.all(),
        # `select2-busqueda` activa el buscador dinámico (inventario/_select2.html,
        # incluido por generar.html) cuando haya muchas plantillas.
        widget=PlantillaSelect(attrs={'class': 'form-select select2-busqueda'}),
        empty_label='— Selecciona una plantilla —',
        label='Plantilla')
    colegio = forms.CharField(max_length=200, label='Colegio')
    # 0–99 impone el supuesto documentado de 1–2 dígitos; la vista lo divide en
    # decena/unidad con zfill(2). Obligatorio solo para PENSAR (ver clean()).
    numero_prueba = forms.IntegerField(
        min_value=0, max_value=99, required=False, label='Número de prueba')
    excel = forms.FileField(
        label='Excel de estudiantes',
        widget=forms.ClearableFileInput(attrs={'accept': '.xlsx'}))

    def clean(self):
        cleaned = super().clean()
        plantilla = cleaned.get('plantilla')
        if (plantilla and plantilla.tipo == PlantillaPersonalizacion.Tipo.PENSAR
                and cleaned.get('numero_prueba') is None):
            self.add_error('numero_prueba',
                           'El número de prueba es obligatorio para plantillas Pensar.')
        return cleaned
