"""Parser del "Reporte de conceptos de órdenes de venta" del ERP externo.

Módulo **PURO** (sin Django/ORM, testeable en unidad), patrón de
`logistica/personalizacion/excel.py`. El reporte es un `.xls` que en realidad es
una **tabla HTML** de ~26 MB (latin-1, `<thead>` con ~45 `<th>`, una fila `<td>`
por artículo de la orden). Se parsea con `html.parser.HTMLParser` alimentado en
chunks con un decodificador incremental, para no cargar 26 MB decodificados de
golpe.

Puntos finos heredados del archivo real:
- Encoding: no trae `<meta charset>` → se asume **latin-1** (nunca falla). Si un
  export futuro declara `charset=utf-8`, se respeta (con `errors='replace'`).
- Columnas por NOMBRE de encabezado, tolerante a orden / mayúsculas / tildes
  (`_norm_encabezado`, patrón de personalización/monitores).
- Celdas con tags anidados (`Vigencia` viene como `<b>Orden anulada</b>`): el
  texto se acumula a través de los tags internos y se limpia.
- `Cantidad` con coma decimal (`17,00`) → `Decimal`; fechas tolerantes
  (inválida → `None`).
- Filas con nº de `<td>` distinto al de `<th>`, o sin ID de orden, se cuentan en
  `n_descartadas` y se ignoran.
"""
import codecs
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

# Encabezado normalizado (lower, sin tildes, espacios colapsados) → clave interna.
ENCABEZADOS = {
    'sucursal':                       'sucursal',
    'centro de costos':               'centro_costos',
    'bodega':                         'bodega',
    'id orden':                       'id_orden',
    'ultimo estado orden de venta':   'estado_orden_erp',
    'estado facturacion':             'estado_facturacion',
    'cliente':                        'cliente',
    'id. cliente':                    'id_cliente',
    'telefono':                       'telefono',
    'departamento':                   'departamento',
    'ciudad':                         'ciudad',
    'direccion':                      'direccion',
    'categoria articulo':             'categoria',
    'cod. articulo':                  'cod_articulo',
    'descripcion original':           'descripcion',
    'cantidad':                       'cantidad',
    'vendedor':                       'vendedor',
    'observacion orden':              'observacion',
    'fecha entrega':                  'fecha_entrega',
    'vigencia':                       'vigencia',
    'fecha orden':                    'fecha_orden',
}

# Columnas sin las cuales el reporte no sirve (el ERP siempre las trae). Faltar
# una → `ReporteInvalido`. El resto son opcionales (default '').
OBLIGATORIOS = (
    'id_orden', 'bodega', 'estado_facturacion', 'vigencia', 'categoria',
    'cod_articulo', 'descripcion', 'cantidad', 'fecha_entrega', 'fecha_orden',
)

# clave interna → nombre "bonito" para el mensaje de error.
_DISPLAY = {
    'sucursal': 'Sucursal', 'centro_costos': 'Centro de costos', 'bodega': 'Bodega',
    'id_orden': 'ID orden', 'estado_orden_erp': 'Último estado orden de venta',
    'estado_facturacion': 'Estado facturación', 'cliente': 'Cliente',
    'id_cliente': 'ID. cliente', 'telefono': 'Teléfono',
    'departamento': 'Departamento', 'ciudad': 'Ciudad', 'direccion': 'Dirección',
    'categoria': 'Categoría artículo', 'cod_articulo': 'Cod. artículo',
    'descripcion': 'Descripción original', 'cantidad': 'Cantidad',
    'vendedor': 'Vendedor', 'observacion': 'Observación orden',
    'fecha_entrega': 'Fecha entrega', 'vigencia': 'Vigencia',
    'fecha_orden': 'Fecha orden',
}

_CHUNK = 1 << 20  # 1 MiB


class ReporteInvalido(Exception):
    """El reporte no se pudo leer o le faltan columnas obligatorias."""


@dataclass
class FilaReporte:
    """Una línea del reporte (un artículo de una orden), ya tipada."""
    id_orden: str
    sucursal: str = ''
    centro_costos: str = ''
    bodega: str = ''
    estado_orden_erp: str = ''
    estado_facturacion: str = ''
    cliente: str = ''
    id_cliente: str = ''
    telefono: str = ''
    departamento: str = ''
    ciudad: str = ''
    direccion: str = ''
    categoria: str = ''
    cod_articulo: str = ''
    descripcion: str = ''
    cantidad: Decimal = field(default_factory=lambda: Decimal('0'))
    vendedor: str = ''
    observacion: str = ''
    vigencia: str = ''
    fecha_entrega: date | None = None
    fecha_orden: datetime | None = None
    orden_archivo: int = 0


@dataclass
class ReporteParseado:
    filas: list
    max_fecha_orden: datetime | None
    n_descartadas: int


def _norm_encabezado(valor):
    """lower + sin tildes (NFKD) + espacios colapsados. 'Categoría artículo' →
    'categoria articulo'."""
    texto = ' '.join(str(valor or '').split()).lower()
    return (unicodedata.normalize('NFKD', texto)
            .encode('ascii', 'ignore').decode())


def _limpiar(texto):
    """Colapsa el espacio en blanco (incluidos saltos de línea) y hace strip."""
    return ' '.join((texto or '').split())


def _a_decimal(texto):
    """'17,00' / '1.234,50' → Decimal. Coma = decimal, punto = miles (locale
    colombiano). Vacío o inválido → Decimal('0')."""
    t = (texto or '').strip()
    if not t:
        return Decimal('0')
    if ',' in t:
        t = t.replace('.', '').replace(',', '.')
    try:
        return Decimal(t)
    except (InvalidOperation, ValueError):
        return Decimal('0')


def _a_fecha(texto):
    """'YYYY-MM-DD' → date; inválida/vacía → None."""
    t = (texto or '').strip()
    if not t:
        return None
    try:
        return datetime.strptime(t[:10], '%Y-%m-%d').date()
    except ValueError:
        return None


def _a_datetime(texto):
    """'YYYY-MM-DD HH:MM:SS' (o solo fecha) → datetime; inválida/vacía → None."""
    t = (texto or '').strip()
    if not t:
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(t, fmt)
        except ValueError:
            continue
    return None


def _sniff_encoding(primer_bloque):
    """Decide el encoding por el primer bloque de bytes: `charset=utf-8` en un
    meta → utf-8; si no → latin-1 (nunca falla con los .xls del ERP)."""
    cabeza = (primer_bloque or b'')[:4096].lower()
    if b'charset=utf-8' in cabeza or b'charset="utf-8"' in cabeza:
        return 'utf-8'
    return 'latin-1'


class _ReporteHTMLParser(HTMLParser):
    """Acumula los `<th>` (encabezados) y cada fila de `<td>` (datos). Construye
    los `FilaReporte` al vuelo para no retener las celdas crudas de 11k filas."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.filas = []
        self.n_descartadas = 0
        self.max_fecha_orden = None
        self._headers = []
        self._indices = None          # clave interna → índice de columna
        self._n_columnas = 0
        self._orden_archivo = 0
        # Estado de la fila/celda en curso.
        self._en_celda = False
        self._buffer = []
        self._celdas = []
        self._fila_es_header = False

    # -- tags ---------------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self._celdas = []
            self._fila_es_header = False
        elif tag in ('td', 'th'):
            self._en_celda = True
            self._buffer = []
            if tag == 'th':
                self._fila_es_header = True

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self._en_celda:
            self._en_celda = False
            self._celdas.append(_limpiar(''.join(self._buffer)))
        elif tag == 'tr':
            self._cerrar_fila()

    def handle_data(self, data):
        if self._en_celda:
            self._buffer.append(data)

    # -- lógica -------------------------------------------------------------
    def _cerrar_fila(self):
        if not self._celdas:
            return
        if self._fila_es_header:
            # La primera fila de encabezados manda; ignora headers repetidos.
            if not self._headers:
                self._headers = self._celdas
            return
        self._procesar_datos(self._celdas)

    def _construir_indices(self):
        indices = {}
        for i, cab in enumerate(self._headers):
            clave = _norm_encabezado(cab)
            if clave in ENCABEZADOS:
                indices[ENCABEZADOS[clave]] = i
        faltan = [_DISPLAY[k] for k in OBLIGATORIOS if k not in indices]
        if faltan:
            raise ReporteInvalido(
                'Al reporte le faltan columnas obligatorias: '
                + ', '.join(faltan) + '.')
        self._indices = indices
        self._n_columnas = len(self._headers)

    def _procesar_datos(self, celdas):
        if self._indices is None:
            self._construir_indices()

        # Nº de celdas distinto al de encabezados → fila corrupta.
        if len(celdas) != self._n_columnas:
            self.n_descartadas += 1
            return

        def val(clave):
            idx = self._indices.get(clave)
            return celdas[idx] if idx is not None else ''

        id_orden = val('id_orden').strip()
        if not id_orden:
            self.n_descartadas += 1
            return

        fecha_orden = _a_datetime(val('fecha_orden'))
        fila = FilaReporte(
            id_orden=id_orden,
            sucursal=val('sucursal'),
            centro_costos=val('centro_costos'),
            bodega=val('bodega'),
            estado_orden_erp=val('estado_orden_erp'),
            estado_facturacion=val('estado_facturacion'),
            cliente=val('cliente'),
            id_cliente=val('id_cliente'),
            telefono=val('telefono'),
            departamento=val('departamento'),
            ciudad=val('ciudad'),
            direccion=val('direccion'),
            categoria=val('categoria'),
            cod_articulo=val('cod_articulo'),
            descripcion=val('descripcion'),
            cantidad=_a_decimal(val('cantidad')),
            vendedor=val('vendedor'),
            observacion=val('observacion'),
            vigencia=val('vigencia'),
            fecha_entrega=_a_fecha(val('fecha_entrega')),
            fecha_orden=fecha_orden,
            orden_archivo=self._orden_archivo,
        )
        self._orden_archivo += 1
        self.filas.append(fila)
        if fecha_orden and (self.max_fecha_orden is None
                            or fecha_orden > self.max_fecha_orden):
            self.max_fecha_orden = fecha_orden

    def finalizar(self):
        """Valida los encabezados aunque no haya llegado ninguna fila de datos
        (archivo con thead pero sin filas)."""
        if self._indices is None and self._headers:
            self._construir_indices()


def parsear_reporte(archivo):
    """Parsea el reporte ERP y devuelve un `ReporteParseado`.

    `archivo` es un file-like BINARIO (p. ej. `request.FILES['reporte']` o
    `open(ruta, 'rb')`). Lanza `ReporteInvalido` si faltan columnas obligatorias.
    """
    parser = _ReporteHTMLParser()
    primer = archivo.read(_CHUNK)
    if isinstance(primer, str):
        # Ya viene texto (poco común): aliméntalo directo sin decodificar.
        parser.feed(primer)
        for bloque in iter(lambda: archivo.read(_CHUNK), ''):
            parser.feed(bloque)
    else:
        decoder = codecs.getincrementaldecoder(_sniff_encoding(primer))(
            errors='replace')
        parser.feed(decoder.decode(primer or b''))
        for bloque in iter(lambda: archivo.read(_CHUNK), b''):
            parser.feed(decoder.decode(bloque))
        parser.feed(decoder.decode(b'', final=True))
    parser.close()
    parser.finalizar()

    return ReporteParseado(
        filas=parser.filas,
        max_fecha_orden=parser.max_fecha_orden,
        n_descartadas=parser.n_descartadas,
    )


# ---------------------------------------------------------------------------
# Helper de tests: fabrica los bytes de un reporte a partir de dicts de fila.
# ---------------------------------------------------------------------------

# Orden canónico de columnas y su etiqueta por defecto (labels reales del ERP).
_ORDEN_CAMPOS = list(ENCABEZADOS.values())
_LABEL_POR_CLAVE = {clave: _DISPLAY[clave] for clave in _ORDEN_CAMPOS}


def crear_reporte_bytes(filas, *, encoding='latin-1', columnas=None, labels=None):
    """Construye los bytes de un reporte HTML de prueba.

    `filas` = lista de dicts (claves internas → valor; se escriben crudos, sin
    escapar, para poder inyectar tags como `<b>` en las pruebas de robustez).
    `columnas` = orden de campos a emitir (default `_ORDEN_CAMPOS`); reordénalo
    para barajar o quítale un campo para simular una columna faltante.
    `labels` = override {clave: etiqueta} para probar mayúsculas/tildes.
    `encoding='utf-8'` inserta un `<meta charset=utf-8>` para ejercitar ese
    camino del sniff.
    """
    columnas = columnas if columnas is not None else _ORDEN_CAMPOS
    labels = labels or {}
    heads = ''.join(
        f'<th>{labels.get(c, _LABEL_POR_CLAVE.get(c, c))}</th>' for c in columnas)
    cuerpo = []
    for fila in filas:
        celdas = ''.join(f'<td>{fila.get(c, "")}</td>' for c in columnas)
        cuerpo.append(f'<tr>{celdas}</tr>')
    meta = '<meta charset="utf-8">' if str(encoding).lower().startswith('utf-8') else ''
    html = (f'<html><head>{meta}</head><body>'
            f'<table><thead><tr>{heads}</tr></thead>'
            f'<tbody>{"".join(cuerpo)}</tbody></table></body></html>')
    return html.encode(encoding, errors='replace')
