"""Forms del inventario.

Catálogos (Fase 3): ModelForms simples — los modales de los templates
renderizan los widgets tal cual y un JS mínimo los rellena al editar (por id
`id_<campo>`). Los toggles de activo/activa y el borrado NO van por form: son
acciones POST propias de cada vista (con sus guards).

Documentos (Fase 4): forms de CABECERA solamente (Entrada/Salida/Traslado).
Las líneas NO van por form: el parcial `inventario/_lineas_doc.html` manda
`linea_item`/`linea_cantidad` (listas paralelas) y `parsear_lineas` las
convierte server-side en [(Item, cantidad)] — mismo patrón que los gastos de
viáticos. Los documentos los crean SIEMPRE los servicios, nunca un form.save().
"""
from django import forms

from .models import Bodega, Categoria, Item, Prestamo, Tercero


class _BootstrapMixin:
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


class _BootstrapModelForm(_BootstrapMixin, forms.ModelForm):
    pass


class _BootstrapForm(_BootstrapMixin, forms.Form):
    pass


def _con_buscador(*campos):
    """Marca selects respaldados por datos (bodegas/terceros/categorías) para
    que el template los convierta en buscador dinámico (Select2, clase
    `select2-busqueda` que inicializa inventario/_select2.html). Los selects
    de enums fijos (dirección, unidad, tipo) se quedan nativos a propósito.
    """
    for campo in campos:
        campo.widget.attrs['class'] = 'form-select select2-busqueda'


class CategoriaForm(_BootstrapModelForm):
    class Meta:
        model = Categoria
        fields = ['nombre']


class BodegaForm(_BootstrapModelForm):
    class Meta:
        model = Bodega
        fields = ['nombre', 'ubicacion']


class MaterialForm(_BootstrapForm):
    """Alta/edición de un MATERIAL = (categoría, referencia) con sus 12 grados.

    No es ModelForm porque no mapea a una fila: un material son 12 `Item`
    (0°–11°) que comparten estos campos. La vista los crea/actualiza en grupo.
    """

    categoria = forms.ModelChoiceField(label='Categoría', queryset=None,
                                       empty_label='— Categoría —')
    referencia = forms.CharField(label='Referencia', max_length=100,
                                 required=False)
    unidad_medida = forms.ChoiceField(label='Unidad',
                                      choices=Item.UnidadMedida.choices,
                                      initial=Item.UnidadMedida.UNIDAD)
    descripcion = forms.CharField(label='Descripción', required=False,
                                  widget=forms.Textarea(attrs={'rows': 2}))
    stock_minimo = forms.IntegerField(label='Stock mínimo', min_value=0,
                                      initial=0, required=False)
    valor_unitario = forms.IntegerField(label='Valor unitario', min_value=0,
                                        required=False)
    activo = forms.BooleanField(label='Activo', required=False, initial=True)

    def __init__(self, *args, original=None, **kwargs):
        """`original` = (categoria_id, referencia) del material que se edita
        (None al crear): sirve para excluirlo del chequeo de duplicados."""
        super().__init__(*args, **kwargs)
        self.original = original
        self.fields['categoria'].queryset = Categoria.objects.all()
        _con_buscador(self.fields['categoria'])

    def clean_referencia(self):
        return (self.cleaned_data.get('referencia') or '').strip()

    def clean_stock_minimo(self):
        return self.cleaned_data.get('stock_minimo') or 0

    def clean(self):
        cleaned = super().clean()
        categoria, referencia = cleaned.get('categoria'), cleaned.get('referencia')
        if categoria is None:
            return cleaned
        # Unicidad del MATERIAL: el UniqueConstraint del modelo es por grado y
        # no ve el grupo, así que el duplicado se detecta aquí.
        if self.original != (categoria.pk, referencia or ''):
            if Item.objects.filter(categoria=categoria,
                                   referencia=referencia or '').exists():
                raise forms.ValidationError(
                    'Ya existe un material con esa categoría y referencia.')
        return cleaned


def clave_material(categoria_id, referencia):
    """Identificador de un material en los formularios: `'<cat_id>:<ref>'`.
    La referencia puede contener ':' → el parseo parte solo en el primero."""
    return f'{categoria_id}:{referencia}'


def parsear_clave_material(valor):
    """Inversa de `clave_material`. Devuelve (categoria_id:int, referencia:str)
    o None si la clave viene vacía o mal formada."""
    if not valor or ':' not in valor:
        return None
    cat_id, _, referencia = valor.partition(':')
    if not cat_id.isdigit():
        return None
    return int(cat_id), referencia


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


# ---------------------------------------------------------------------------
# Documentos (Fase 4): cabeceras
# ---------------------------------------------------------------------------

def _bodegas_activas():
    return Bodega.objects.filter(activa=True)


class EntradaForm(_BootstrapForm):
    bodega = forms.ModelChoiceField(label='Bodega', queryset=None,
                                    empty_label='— Bodega —')
    proveedor = forms.CharField(label='Proveedor', max_length=200,
                                required=False)
    observaciones = forms.CharField(label='Observaciones', required=False,
                                    widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['bodega'].queryset = _bodegas_activas()
        _con_buscador(self.fields['bodega'])


class SalidaForm(_BootstrapForm):
    bodega = forms.ModelChoiceField(label='Bodega', queryset=None,
                                    empty_label='— Bodega —')
    # Opcional: una salida puede ser consumo interno sin destinatario. El alta
    # al vuelo la resuelve el AJAX de terceros (F3) sin abandonar el form.
    tercero = forms.ModelChoiceField(label='Tercero (destinatario)',
                                     queryset=None, required=False,
                                     empty_label='— Sin tercero —')
    motivo = forms.CharField(label='Motivo', max_length=200, required=False)
    observaciones = forms.CharField(label='Observaciones', required=False,
                                    widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['bodega'].queryset = _bodegas_activas()
        self.fields['tercero'].queryset = Tercero.objects.filter(activo=True)
        _con_buscador(self.fields['bodega'], self.fields['tercero'])


class TrasladoForm(_BootstrapForm):
    bodega_origen = forms.ModelChoiceField(label='Bodega de origen',
                                           queryset=None,
                                           empty_label='— Origen —')
    bodega_destino = forms.ModelChoiceField(label='Bodega de destino',
                                            queryset=None,
                                            empty_label='— Destino —')
    observaciones = forms.CharField(label='Observaciones', required=False,
                                    widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['bodega_origen'].queryset = _bodegas_activas()
        self.fields['bodega_destino'].queryset = _bodegas_activas()
        _con_buscador(self.fields['bodega_origen'],
                      self.fields['bodega_destino'])

    def clean(self):
        cleaned = super().clean()
        origen, destino = cleaned.get('bodega_origen'), cleaned.get('bodega_destino')
        if origen and destino and origen == destino:
            raise forms.ValidationError(
                'La bodega de origen y la de destino deben ser distintas.')
        return cleaned


class PrestamoForm(_BootstrapForm):
    # OTORGADO descuenta stock al crear; RECIBIDO lo suma (nos prestan) y la
    # fecha compromiso pasa a ser cuándo debemos devolver NOSOTROS. El texto
    # de ayuda vive en el template (prestamo_form.html).
    direccion = forms.ChoiceField(label='Dirección',
                                  choices=Prestamo.Direccion.choices,
                                  initial=Prestamo.Direccion.OTORGADO)
    tercero = forms.ModelChoiceField(label='Tercero', queryset=None,
                                     empty_label='— Tercero —')
    fecha_compromiso = forms.DateField(
        label='Fecha compromiso',
        widget=forms.DateInput(attrs={'type': 'date'}))
    observaciones = forms.CharField(label='Observaciones', required=False,
                                    widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tercero'].queryset = Tercero.objects.filter(activo=True)
        _con_buscador(self.fields['tercero'])


def parsear_lineas(post, *, con_bodega=False):
    """Convierte el POST del parcial `_lineas_doc.html` en líneas de servicio.

    Lee las listas paralelas `linea_item`/`linea_cantidad` (y `linea_bodega`
    si `con_bodega` — lo usará el form de préstamos en F5) y devuelve
    [(Item, cantidad)] o [(Item, Bodega, cantidad)]. Las filas totalmente
    vacías se ignoran (las deja el botón −); cualquier otra inconsistencia
    lanza ValueError con mensaje legible para `messages.error`.
    """
    ids = post.getlist('linea_item')
    cantidades = post.getlist('linea_cantidad')
    bodegas = post.getlist('linea_bodega') if con_bodega else [''] * len(ids)

    lineas = []
    for item_id, cant, bodega_id in zip(ids, cantidades, bodegas):
        item_id, cant, bodega_id = item_id.strip(), cant.strip(), bodega_id.strip()
        if not item_id and not cant:
            continue
        if not item_id:
            raise ValueError('Hay una línea sin artículo seleccionado.')
        try:
            cantidad = int(cant)
        except ValueError:
            raise ValueError('Hay una línea con cantidad inválida.')
        if cantidad <= 0:
            raise ValueError('Las cantidades deben ser mayores que cero.')
        if not item_id.isdigit():
            raise ValueError('Hay una línea con un artículo inválido o inactivo.')
        item = Item.objects.filter(pk=item_id, activo=True).first()
        if item is None:
            raise ValueError('Hay una línea con un artículo inválido o inactivo.')
        if con_bodega:
            if not bodega_id.isdigit():
                raise ValueError('Hay una línea sin bodega válida.')
            bodega = Bodega.objects.filter(pk=bodega_id, activa=True).first()
            if bodega is None:
                raise ValueError('Hay una línea sin bodega válida.')
            lineas.append((item, bodega, cantidad))
        else:
            lineas.append((item, cantidad))
    if not lineas:
        raise ValueError('El documento necesita al menos una línea.')
    return lineas
