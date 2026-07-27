"""Forms de despachos.

`CargaReporteForm` — subida del reporte ERP diario. El límite de tamaño y la
extensión se validan aquí (NO en el parser puro): el archivo real es un `.xls`
que en realidad es HTML de ~26 MB, así que se admite `.xls/.html/.htm` y hasta
80 MB (margen amplio sobre los 26 MB observados).
"""
from django import forms

# 80 MiB — el reporte real pesa ~26 MB; el margen cubre crecimiento del catálogo.
MAX_BYTES = 80 * 1024 * 1024
EXTENSIONES = ('.xls', '.html', '.htm')


class CargaReporteForm(forms.Form):
    archivo = forms.FileField(
        label='Reporte de órdenes de venta (.xls)',
        widget=forms.ClearableFileInput(
            attrs={'accept': '.xls,.html,.htm', 'class': 'form-control'}))

    def clean_archivo(self):
        archivo = self.cleaned_data['archivo']
        nombre = (archivo.name or '').lower()
        if not nombre.endswith(EXTENSIONES):
            raise forms.ValidationError(
                'El archivo debe ser el reporte del ERP (.xls, .html o .htm).')
        if archivo.size > MAX_BYTES:
            raise forms.ValidationError(
                f'El archivo supera el límite de {MAX_BYTES // (1024 * 1024)} MB.')
        return archivo
