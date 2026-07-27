"""Ayudas compartidas por los tests del inventario.

No se llama `test_*` a propósito: el descubrimiento de Django no debe tomarlo
por un módulo de tests.
"""
from logistica.inventario.models import GRADOS, Categoria, Item


def crear_item(categoria=None, referencia='REF', grado=0, **kw):
    """Un `Item` suelto (un material EN UN grado).

    La UI crea siempre los 12 grados de un material; los tests de dominio no
    los necesitan, así que esta factory crea solo el que se va a mover.
    """
    if categoria is None:
        categoria, _ = Categoria.objects.get_or_create(nombre='General')
    return Item.objects.create(categoria=categoria, referencia=referencia,
                               grado=grado, **kw)


def crear_material(categoria=None, referencia='REF', grados=GRADOS, **kw):
    """El material completo: un `Item` por grado, como lo crea la UI.
    Devuelve {grado: Item} (los tests de captura por grados lo necesitan)."""
    return {grado: crear_item(categoria=categoria, referencia=referencia,
                              grado=grado, **kw)
            for grado in grados}


def _clave(material):
    """Acepta un `Item` (usa su `clave_material`), un dict {grado: Item} (el
    que devuelve `crear_material`) o la clave cruda en texto."""
    if isinstance(material, dict):
        material = next(iter(material.values()))
    return material if isinstance(material, str) else material.clave_material


def lineas_post(filas, *, con_bodega=False):
    """Las listas paralelas que manda el parcial `_lineas_material.html`.

    ``filas`` = [(material, cantidades)] — o [(material, bodega, cantidades)]
    con ``con_bodega=True``. ``material`` es un Item/dict de material/clave
    cruda (o '' para una fila en blanco) y ``cantidades`` = {grado: valor}.
    Como el navegador, cada fila manda SIEMPRE sus 12 celdas: las que no
    llevan cantidad van vacías.
    """
    datos = {'linea_material': [], **{f'linea_g{g}': [] for g in GRADOS}}
    if con_bodega:
        datos['linea_bodega'] = []
    for fila in filas:
        if con_bodega:
            material, bodega, cantidades = fila
            datos['linea_bodega'].append(
                str(getattr(bodega, 'pk', bodega)) if bodega else '')
        else:
            material, cantidades = fila
        datos['linea_material'].append(_clave(material) if material else '')
        for grado in GRADOS:
            valor = cantidades.get(grado, '')
            datos[f'linea_g{grado}'].append('' if valor == '' else str(valor))
    return datos
