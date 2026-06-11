"""Forms de los catálogos del inventario (Fase 3).

ModelForms simples: los modales de los templates renderizan los widgets tal
cual y un JS mínimo los rellena al editar (por id `id_<campo>`). Los toggles de
activo/activa y el borrado NO van por form: son acciones POST propias de cada
vista (con sus guards).
"""
from django import forms

from .models import Bodega, Categoria, Item, Tercero


class _BootstrapModelForm(forms.ModelForm):
    """Aplica las clases Bootstrap a todos los widgets de una vez."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            widget = campo.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault('class', 'form-check-input')
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault('class', 'form-select')
            else:
                widget.attrs.setdefault('class', 'form-control')


class CategoriaForm(_BootstrapModelForm):
    class Meta:
        model = Categoria
        fields = ['nombre']


class BodegaForm(_BootstrapModelForm):
    class Meta:
        model = Bodega
        fields = ['nombre', 'ubicacion']


class ItemForm(_BootstrapModelForm):
    class Meta:
        model = Item
        fields = ['codigo', 'nombre', 'categoria', 'unidad_medida',
                  'descripcion', 'stock_minimo', 'valor_unitario', 'activo']
        widgets = {'descripcion': forms.Textarea(attrs={'rows': 2})}


class TerceroForm(_BootstrapModelForm):
    class Meta:
        model = Tercero
        fields = ['nombre', 'documento', 'telefono', 'notas']
        widgets = {'notas': forms.Textarea(attrs={'rows': 2})}

    def clean_documento(self):
        # La unicidad real la da el UniqueConstraint condicional del modelo;
        # se valida aquí para dar un mensaje claro en español (y porque el
        # constraint permite repetir el documento vacío).
        documento = (self.cleaned_data.get('documento') or '').strip()
        if documento:
            qs = Tercero.objects.filter(documento=documento)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    'Ya existe un tercero con ese documento.')
        return documento
