"""Forms del inventario.

Catálogos (Fase 3): ModelForms simples — los modales de los templates
renderizan los widgets tal cual y un JS mínimo los rellena al editar (por id
`id_<campo>`). Los toggles de activo/activa y el borrado NO van por form: son
acciones POST propias de cada vista (con sus guards).

Documentos: forms de CABECERA solamente (Entrada/Salida/Traslado/Préstamo).
Las líneas NO van por form: el parcial `inventario/_lineas_material.html` manda
`linea_material` + `linea_g0`…`linea_g11` (listas paralelas) y
`parsear_lineas_material` las convierte server-side en [(Item, cantidad)] —
mismo patrón que los gastos de viáticos. Los documentos los crean SIEMPRE los
servicios, nunca un form.save().
"""
from django import forms

from .models import GRADOS, Bodega, Categoria, Item, Prestamo, Tercero
from .permisos import (bodega_asignada, bodegas_escribibles, es_restringido,
                       puede_escribir_en)


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


def parsear_clave_material(valor):
    """Inversa de `Item.clave_material` (`'<cat_id>:<ref>'`): devuelve
    (categoria_id:int, referencia:str), o None si viene vacía o mal formada.
    La referencia puede contener ':' → se parte solo en el primero."""
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


def _bodegas_para(usuario):
    """Bodegas activas que `usuario` puede OPERAR (escribir).

    Sin asignación y superusuario → todas las activas, que es exactamente el
    comportamiento histórico (por eso `usuario=None` es un default seguro).
    """
    return bodegas_escribibles(usuario).filter(activa=True)


def _restringir_bodega(campo, usuario, *, mensaje=None):
    """Recorta el `<select>` de bodega a las que el usuario puede operar.

    Es la PRIMERA barrera server-side: un POST forjado con una bodega ajena no
    está en el queryset y cae en `invalid_choice` — de ahí el mensaje propio,
    porque el de Django ("Escoja una opción válida") haría pensar en un bug de
    la página en vez de en un permiso. La segunda barrera es `exigir_bodega`
    en la vista, antes de llamar al servicio.
    """
    campo.queryset = _bodegas_para(usuario)
    asignada = bodega_asignada(usuario) if es_restringido(usuario) else None
    if asignada is None:
        return
    campo.error_messages['invalid_choice'] = mensaje or (
        f'Solo puedes registrar movimientos en tu bodega ("{asignada}").')
    # Con una sola opción el placeholder solo estorba: se preselecciona.
    if campo.queryset.count() == 1:
        campo.initial = campo.queryset.first().pk
        campo.empty_label = None


class EntradaForm(_BootstrapForm):
    bodega = forms.ModelChoiceField(label='Bodega', queryset=None,
                                    empty_label='— Bodega —')
    proveedor = forms.CharField(label='Proveedor', max_length=200,
                                required=False)
    observaciones = forms.CharField(label='Observaciones', required=False,
                                    widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        _restringir_bodega(self.fields['bodega'], usuario)
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

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        _restringir_bodega(self.fields['bodega'], usuario)
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

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo el ORIGEN se restringe: sacar material de la propia sede hacia
        # otra es la operación real; jalarlo de una sede ajena, no.
        asignada = bodega_asignada(usuario) if es_restringido(usuario) else None
        _restringir_bodega(
            self.fields['bodega_origen'], usuario,
            mensaje=(f'Solo puedes trasladar DESDE tu bodega ("{asignada}").'
                     if asignada else None))
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


def _cantidad_de_celda(crudo, grado):
    """Valor de una celda de grado: None si viene vacía, entero > 0 si trae
    cantidad. El 0 se trata como "ese grado no va" (es lo que el usuario
    escribe al corregirse), no como error."""
    crudo = crudo.strip()
    if not crudo:
        return None
    try:
        cantidad = int(crudo)
    except ValueError:
        raise ValueError(f'Hay una cantidad inválida en el grado {grado}°.')
    if cantidad < 0:
        raise ValueError('Las cantidades deben ser mayores que cero.')
    return cantidad or None


def parsear_lineas_material(post, *, con_bodega=False, usuario=None):
    """Convierte el POST de `_lineas_material.html` en líneas de servicio.

    Cada fila del formulario es un MATERIAL con sus 12 cantidades por grado
    (como la hoja de cálculo del usuario), pero la unidad que se mueve sigue
    siendo el `Item` por grado: una fila se EXPANDE a una línea de servicio
    por grado con cantidad > 0. Lee las listas paralelas `linea_material`
    (clave `'<categoria_id>:<referencia>'`), `linea_g0`…`linea_g11` y
    `linea_bodega` (solo si `con_bodega`, préstamos).

    Con `usuario` (y solo entonces) valida además que la bodega de cada fila
    sea operable por esa persona: en los préstamos la bodega va POR LÍNEA, así
    que no hay form de cabecera donde recortar el queryset. El default `None`
    deja intacto todo lo que no manda usuario (devoluciones y los tests).

    Devuelve [(Item, cantidad)] o [(Item, Bodega, cantidad)] — el contrato que
    ya esperan los servicios, que NO cambian. Las filas totalmente vacías se
    ignoran (las deja el botón −); cualquier otra inconsistencia lanza
    ValueError con mensaje legible para `messages.error`.
    """
    claves = post.getlist('linea_material')
    # Una columna por grado; cada lista es paralela a `claves` por índice de fila.
    columnas = {grado: post.getlist(f'linea_g{grado}') for grado in GRADOS}
    bodegas = post.getlist('linea_bodega') if con_bodega else [''] * len(claves)

    lineas = []
    for fila, clave in enumerate(claves):
        clave = clave.strip()
        cantidades = {}
        for grado in GRADOS:
            columna = columnas[grado]
            crudo = columna[fila] if fila < len(columna) else ''
            cantidad = _cantidad_de_celda(crudo, grado)
            if cantidad is not None:
                cantidades[grado] = cantidad

        if not clave and not cantidades:
            continue
        if not clave:
            raise ValueError('Hay una línea sin material seleccionado.')

        par = parsear_clave_material(clave)
        if par is None:
            raise ValueError('Hay una línea con un material inválido o inactivo.')
        categoria_id, referencia = par
        items = {i.grado: i for i in Item.objects.filter(
            categoria_id=categoria_id, referencia=referencia, activo=True)}
        if not items:
            raise ValueError('Hay una línea con un material inválido o inactivo.')
        etiqueta = next(iter(items.values())).material
        if not cantidades:
            raise ValueError(f'La línea de "{etiqueta}" no tiene cantidades: '
                             f'escribe al menos un grado.')

        bodega = None
        if con_bodega:
            bodega_id = (bodegas[fila] if fila < len(bodegas) else '').strip()
            bodega = (Bodega.objects.filter(pk=bodega_id, activa=True).first()
                      if bodega_id.isdigit() else None)
            if bodega is None:
                raise ValueError('Hay una línea sin bodega válida.')
            # Mensaje DISTINTO del de arriba a propósito: "no puedes operarla"
            # y "no existe/está inactiva" son problemas diferentes y el usuario
            # tiene que poder distinguirlos.
            if usuario is not None and not puede_escribir_en(usuario, bodega):
                raise ValueError(
                    f'No puedes registrar movimientos en "{bodega.nombre}": tu '
                    f'bodega asignada es "{bodega_asignada(usuario)}".')

        for grado, cantidad in sorted(cantidades.items()):
            item = items.get(grado)
            if item is None:
                raise ValueError(f'"{etiqueta}" no existe en el grado {grado}°.')
            lineas.append((item, bodega, cantidad) if con_bodega
                          else (item, cantidad))

    if not lineas:
        raise ValueError('El documento necesita al menos una línea.')
    return lineas
