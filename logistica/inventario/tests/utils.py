"""Ayudas compartidas por los tests del inventario.

No se llama `test_*` a propósito: el descubrimiento de Django no debe tomarlo
por un módulo de tests.
"""
from logistica.inventario.models import Categoria, Item


def crear_item(categoria=None, referencia='REF', grado=0, **kw):
    """Un `Item` suelto (un material EN UN grado).

    La UI crea siempre los 12 grados de un material; los tests de dominio no
    los necesitan, así que esta factory crea solo el que se va a mover.
    """
    if categoria is None:
        categoria, _ = Categoria.objects.get_or_create(nombre='General')
    return Item.objects.create(categoria=categoria, referencia=referencia,
                               grado=grado, **kw)
