"""Lectura del Excel de estudiantes (openpyxl, sin pandas).

Réplica del patrón de `programacion/monitores/views.py`: encabezados tolerantes
a orden/mayúsculas, `load_workbook(read_only=True, data_only=True)`,
`iter_rows(values_only=True)`. Columnas esperadas: `Nombres`, `Grado`, `Usuario`.
Devuelve `list[dict]` con claves `nombre`/`grado`/`usuario`. Omite las filas sin
`Nombres`. Si faltan columnas → `ExcelInvalido`.
"""
from openpyxl import load_workbook

# Encabezado normalizado (lower) → clave de salida.
_COLUMNAS = {
    'nombres': 'nombre',
    'grado':   'grado',
    'usuario': 'usuario',
}


class ExcelInvalido(Exception):
    """El Excel no se pudo leer o le faltan columnas obligatorias."""


def _norm(valor):
    """None→'', número entero→int, y str().strip()."""
    if valor is None:
        return ''
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor).strip()


def _entero_texto(valor):
    """Como `_norm` pero además quita el sufijo '.0' que openpyxl deja al leer
    un entero como float (5 → 5.0 → '5'). Para grado/usuario numéricos."""
    texto = _norm(valor)
    if texto.endswith('.0') and texto[:-2].isdigit():
        return texto[:-2]
    return texto


def leer_estudiantes(archivo):
    """Lee el .xlsx subido y devuelve `list[dict]` de estudiantes.

    `archivo` es un file-like (p. ej. `request.FILES['excel']`). Lanza
    `ExcelInvalido` si el archivo no se puede abrir o faltan columnas.
    """
    try:
        wb = load_workbook(archivo, read_only=True, data_only=True)
        ws = wb.active
        filas = ws.iter_rows(values_only=True)
        encabezados = next(filas, None)
    except Exception:
        raise ExcelInvalido('No se pudo leer el Excel: ¿está dañado o vacío?')

    if not encabezados:
        raise ExcelInvalido('El Excel está vacío.')

    # Mapa encabezado-normalizado → índice de columna (tolera orden/mayúsculas).
    indices = {}
    for i, cab in enumerate(encabezados):
        clave = _norm(cab).lower()
        if clave in _COLUMNAS:
            indices[_COLUMNAS[clave]] = i

    faltan = [nom for nom, clave in _COLUMNAS.items() if clave not in indices]
    if faltan:
        raise ExcelInvalido(
            'Al Excel le faltan columnas obligatorias: '
            + ', '.join(sorted(faltan))
            + '. Se esperan: Nombres, Grado, Usuario.')

    def celda(fila, clave):
        idx = indices[clave]
        return fila[idx] if idx < len(fila) else ''

    estudiantes = []
    for fila in filas:
        if not fila:
            continue
        nombre = _norm(celda(fila, 'nombre'))
        if not nombre:  # fila sin nombre = fila vacía → se omite
            continue
        estudiantes.append({
            'nombre':  nombre,
            'grado':   _entero_texto(celda(fila, 'grado')),
            'usuario': _entero_texto(celda(fila, 'usuario')),
        })
    return estudiantes
