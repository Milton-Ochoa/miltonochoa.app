from django import forms

from .models import ColegioSimulacro, Monitor


class MonitorForm(forms.ModelForm):
    """Formulario del monitor (espejo reducido de ``ProfesorForm``).

    La cascada departamento→ciudad se resuelve en el template con el mismo JS y
    el JSON ``DEPARTAMENTOS_CIUDADES`` que usa profesores; aquí ambos quedan como
    ``Select`` para que el widget renderice y la validación acepte cualquier valor
    del catálogo geográfico.
    """

    class Meta:
        model  = Monitor
        fields = [
            'nombre', 'apellido', 'documento', 'celular',
            'departamento', 'ciudad',
            'banco', 'tipo_cuenta', 'cuenta_bancaria',
        ]
        widgets = {
            'nombre':          forms.TextInput(attrs={'class': 'form-control'}),
            'apellido':        forms.TextInput(attrs={'class': 'form-control'}),
            'documento':       forms.TextInput(attrs={'class': 'form-control'}),
            'celular':         forms.TextInput(attrs={'class': 'form-control'}),
            'departamento':    forms.Select(attrs={'class': 'form-select'}),
            'ciudad':          forms.Select(attrs={'class': 'form-select'}),
            'banco':           forms.Select(attrs={'class': 'form-select'}),
            'tipo_cuenta':     forms.Select(attrs={'class': 'form-select'}),
            'cuenta_bancaria': forms.TextInput(attrs={'class': 'form-control'}),
        }


class ColegioSimulacroForm(forms.ModelForm):
    """Alta/edición de un colegio de simulacro (catálogo propio).

    La cascada departamento→ciudad se resuelve en el template con el mismo JS y
    el JSON ``DEPARTAMENTOS_CIUDADES`` que usan profesores/monitores.
    """

    class Meta:
        model  = ColegioSimulacro
        fields = ['nombre', 'codigo', 'departamento', 'ciudad']
        widgets = {
            'nombre':       forms.TextInput(attrs={'class': 'form-control'}),
            'codigo':       forms.TextInput(attrs={'class': 'form-control'}),
            'departamento': forms.Select(attrs={'class': 'form-select'}),
            'ciudad':       forms.Select(attrs={'class': 'form-select'}),
        }
