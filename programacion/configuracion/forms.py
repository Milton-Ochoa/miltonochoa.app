from django import forms
from .models import Colegio, Profesor
from .colombia_geo import DEPARTAMENTOS
from datetime import date


class ColegioForm(forms.ModelForm):
    """Formulario para crear y editar colegios."""

    departamento = forms.ChoiceField(
        choices=[('', 'Seleccionar departamento...')] + [(d, d) for d in DEPARTAMENTOS],
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_departamento'}),
    )
    ciudad = forms.CharField(
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_ciudad'}),
    )

    class Meta:
        model  = Colegio
        fields = ['codigo', 'nombre', 'calendario', 'departamento', 'ciudad',
                  'direccion', 'observacion', 'mapa_link']
        widgets = {
            'calendario':  forms.Select(attrs={'class': 'form-select'}),
            'codigo':      forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'Ej: COL-001'}),
            'nombre':      forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'Ej: Liceo Campestre'}),
            'direccion':   forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'Ej: Cra 5 # 10-20'}),
            'observacion': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 2,
                'placeholder': 'Observaciones adicionales...'}),
            'mapa_link':   forms.URLInput(attrs={
                'class': 'form-control', 'placeholder': 'https://maps.google...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Si hay una instancia con ciudad, construir las opciones del select
        if self.instance and self.instance.pk and self.instance.ciudad:
            from .colombia_geo import ciudades_de
            ciudades = ciudades_de(self.instance.departamento)
            ciudad_actual = self.instance.ciudad
            # Aseguramos que la ciudad actual esté en las opciones
            if ciudad_actual not in ciudades:
                ciudades = sorted([ciudad_actual] + ciudades)
            self.fields['ciudad'].widget.choices = (
                [('', 'Seleccionar ciudad...')] + [(c, c) for c in ciudades]
            )
        else:
            self.fields['ciudad'].widget.choices = [('', 'Seleccionar departamento primero...')]


class ProfesorForm(forms.ModelForm):
    """Formulario completo del profesor."""
    class Meta:
        model  = Profesor
        fields = [
            'nombre', 'apellido', 'documento', 'fecha_nacimiento',
            'estado_civil', 'talla_camisa',
            'email', 'celular', 'departamento', 'ciudad', 'direccion',
            'materias', 'disponibilidad', 'eps', 'fondo_pension',
            'banco', 'tipo_cuenta', 'cuenta_bancaria',
        ]
        widgets = {
            'nombre':           forms.TextInput(attrs={'class': 'form-control'}),
            'apellido':         forms.TextInput(attrs={'class': 'form-control'}),
            'documento':        forms.TextInput(attrs={'class': 'form-control'}),
            'fecha_nacimiento': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'estado_civil':     forms.Select(attrs={'class': 'form-select'}),
            'talla_camisa':     forms.TextInput(attrs={'class': 'form-control'}),
            'email':            forms.EmailInput(attrs={'class': 'form-control'}),
            'celular':          forms.TextInput(attrs={'class': 'form-control'}),
            'departamento':     forms.Select(attrs={'class': 'form-select'}),
            'ciudad':           forms.Select(attrs={'class': 'form-select'}),
            'direccion':        forms.TextInput(attrs={'class': 'form-control'}),
            'materias':         forms.SelectMultiple(attrs={'class': 'form-select'}),
            'disponibilidad':   forms.TextInput(attrs={'class': 'form-control'}),
            'eps':              forms.Select(attrs={'class': 'form-select'}),
            'fondo_pension':    forms.Select(attrs={'class': 'form-select'}),
            'banco':            forms.Select(attrs={'class': 'form-select'}),
            'tipo_cuenta':      forms.Select(attrs={'class': 'form-select'}),
            'cuenta_bancaria':  forms.TextInput(attrs={'class': 'form-control'}),
        }