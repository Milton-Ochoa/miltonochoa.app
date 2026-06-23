from django import forms

from programacion.colegios.models import Grado

from .models import ColegioSimulacro, Monitor, Simulacro


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


class SimulacroForm(forms.ModelForm):
    """Alta/edición de un simulacro.

    ``grados`` es un M2M plano al catálogo global (multiselect Select2 en el
    template). Los ``monitores`` NO van en el form: su M2M usa ``through``
    (``AsignacionMonitor``), que Django no admite en un ModelForm → se sincronizan
    a mano en la vista a partir de las ids del POST.
    """

    grados = forms.ModelMultipleChoiceField(
        queryset=Grado.objects.all(), required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-select select2-grados'}))

    class Meta:
        model  = Simulacro
        fields = ['colegio', 'fecha', 'grados', 'jornada', 'valor', 'observaciones']
        widgets = {
            'colegio':       forms.Select(attrs={'class': 'form-select select2-colegio'}),
            'fecha':         forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'jornada':       forms.Select(attrs={'class': 'form-select'}),
            'valor':         forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'observaciones': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo colegios activos en el alta; al editar, conserva el ya elegido aunque
        # esté inactivo para no perderlo del select.
        qs = ColegioSimulacro.objects.filter(activo=True)
        if self.instance.pk and self.instance.colegio_id:
            qs = qs | ColegioSimulacro.objects.filter(pk=self.instance.colegio_id)
        self.fields['colegio'].queryset = qs.distinct().order_by('nombre')
        self.fields['colegio'].required = True
