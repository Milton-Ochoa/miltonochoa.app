"""Form de cabecera de la devolución de colegio.

Las líneas NO van por form: las manda el parcial compartido
`inventario/_lineas_material.html` (un material con sus 12 cantidades por grado)
y las parsea `inventario.forms.parsear_lineas_material`. Aquí `con_bodega=False`
—la bodega es de la devolución completa, no por línea— a diferencia de los
préstamos.
"""
from django import forms

# Helpers de la sub-app dueña del dominio (mismo patrón que financiera.pagos
# reutilizando programacion.pagos).
from logistica.inventario.forms import (_BootstrapForm, _con_buscador,
                                        _restringir_bodega)


class DevolucionColegioForm(_BootstrapForm):
    fecha_recibido = forms.DateField(
        label='Fecha de recibido',
        widget=forms.DateInput(attrs={'type': 'date'}))
    # Texto libre con autocompletado: el catálogo de colegios vive en el ERP de
    # despachos (`OrdenDespacho`), que no siempre trae el que devuelve.
    colegio = forms.CharField(label='Colegio', max_length=200,
                              widget=forms.TextInput(
                                  attrs={'list': 'colegios_erp',
                                         'autocomplete': 'off'}))
    codigo_colegio = forms.CharField(label='Código', max_length=60,
                                     required=False)
    regional = forms.CharField(label='Regional', max_length=120, required=False)
    ejecutivo = forms.CharField(label='Ejecutivo', max_length=200,
                                required=False)
    bodega = forms.ModelChoiceField(label='Bodega de ingreso', queryset=None,
                                    empty_label='— Bodega —')
    # El material llegó pero no se acepta: queda el registro (qué vino y por
    # qué se rechazó) sin sumar a existencias.
    no_valida = forms.BooleanField(
        label='Devolución no válida (no suma a existencias)', required=False)
    motivo_no_valida = forms.CharField(
        label='Motivo del rechazo', max_length=250, required=False)
    observaciones = forms.CharField(label='Observaciones', required=False,
                                    widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Quien opera una bodega solo puede ingresar devoluciones a la suya.
        _restringir_bodega(self.fields['bodega'], usuario)
        _con_buscador(self.fields['bodega'])

    def clean_colegio(self):
        return (self.cleaned_data.get('colegio') or '').strip()

    def clean_motivo_no_valida(self):
        return (self.cleaned_data.get('motivo_no_valida') or '').strip()

    def clean(self):
        """El motivo es obligatorio al rechazar (el servicio y el CHECK de BD lo
        vuelven a exigir; aquí es para que el error salga en el campo)."""
        datos = super().clean()
        if datos.get('no_valida') and not datos.get('motivo_no_valida'):
            self.add_error('motivo_no_valida',
                           'Indica por qué la devolución no es válida.')
        elif not datos.get('no_valida'):
            datos['motivo_no_valida'] = ''
        return datos
