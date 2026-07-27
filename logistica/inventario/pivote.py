"""Pivote del inventario: de filas por (material, grado) a filas por MATERIAL
con una columna por grado.

Vive aparte de `views.py` porque lo comparten la lista de artículos, las
existencias y sus exports — y lo reutilizarán las devoluciones de colegios
(F5), que se capturan y se exportan con el mismo layout de 12 grados.

Contrato de cada fila devuelta:

    clave           (categoria_id, referencia): identifica al MATERIAL
    clave_material  la misma clave en el formato de los forms ('<id>:<ref>')
    categoria / referencia / material
    muestra         un Item cualquiera del grupo — los campos compartidos
                    (unidad, mínimo, valor, activo) son idénticos en los 12
    celdas          12 dicts {grado, item|None, cantidad}, en orden 0°→11°
    total           suma de las celdas

Los items deben venir con `select_related('categoria')`: las properties
`material`/`nombre`/`clave_material` la leen (un N+1 por fila sin eso).
"""
from .models import GRADO_MAX, GRADO_MIN, GRADOS


def _stock_total(item):
    return getattr(item, 'stock_total', 0) or 0


def agrupar_materiales(items, *, cantidad=_stock_total):
    """Agrupa `Item` en filas de material con una celda por grado.

    `cantidad(item)` es lo que se pinta en la celda; por defecto la annotation
    `stock_total`. El orden de salida es el de `items` (que las vistas piden
    por categoría, referencia y grado), así que la tabla sale ya ordenada.
    """
    filas = {}
    for item in items:
        clave = (item.categoria_id, item.referencia)
        fila = filas.get(clave)
        if fila is None:
            fila = filas[clave] = {
                'clave': clave,
                'clave_material': item.clave_material,
                'categoria': item.categoria,
                'referencia': item.referencia,
                'material': item.material,
                'muestra': item,
                'celdas': [{'grado': g, 'item': None, 'cantidad': 0}
                           for g in GRADOS],
                'total': 0,
            }
        # Un grado fuera de rango solo llegaría de datos corruptos (el CHECK
        # del modelo lo impide): se ignora en vez de reventar la tabla.
        if GRADO_MIN <= item.grado <= GRADO_MAX:
            celda = fila['celdas'][item.grado - GRADO_MIN]
            celda['item'] = item
            celda['cantidad'] = cantidad(item)
            fila['total'] += celda['cantidad']
    return list(filas.values())


def agrupar_materiales_por_bodega(items, stocks):
    """Filas por (material, bodega): las existencias pivotadas.

    `items` son TODOS los items de los materiales implicados — no solo los que
    tienen fila de `Stock` — para que cada grado tenga su celda ajustable
    aunque nunca haya movido existencia (el ajuste crea la fila de Stock si
    falta). `stocks` aporta las cantidades: una bodega aparece para un material
    solo si tiene al menos una fila de Stock suya, así una bodega que nunca lo
    tocó no ensucia la tabla.
    """
    cantidades = {}
    bodegas_por_material = {}
    for s in stocks:
        cantidades[(s.item_id, s.bodega_id)] = s.cantidad
        clave = (s.item.categoria_id, s.item.referencia)
        bodegas_por_material.setdefault(clave, {})[s.bodega_id] = s.bodega

    filas = []
    for grupo in agrupar_materiales(items, cantidad=lambda item: 0):
        bodegas = bodegas_por_material.get(grupo['clave'], {}).values()
        for bodega in sorted(bodegas, key=lambda b: b.nombre):
            celdas = [{
                'grado': celda['grado'],
                'item': celda['item'],
                'cantidad': (cantidades.get((celda['item'].pk, bodega.pk), 0)
                             if celda['item'] else 0),
            } for celda in grupo['celdas']]
            filas.append({**grupo, 'bodega': bodega, 'celdas': celdas,
                          'total': sum(c['cantidad'] for c in celdas)})
    return filas
