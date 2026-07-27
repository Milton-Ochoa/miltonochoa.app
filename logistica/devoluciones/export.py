"""Pivote, detalle en pantalla y Excel de las devoluciones de colegios.

Vive aparte de `views.py` porque financiera lo reutiliza tal cual en su vista de
solo lectura: el layout de la hoja (una fila por devolución y material, con los
12 grados en columnas) debe ser IDÉNTICO en las dos áreas.

`filas_detalle` es la fuente ÚNICA de ese layout: la tabla "Detalle por material"
de las dos áreas y el Excel salen de ella, así lo que se ve en pantalla y lo que
se descarga no pueden divergir (que es justo lo que pidió el usuario: dejar de
bajar el Excel solo para ver el detalle).

La columna "Registro Effi" de la hoja original se omite a propósito (es el
número de orden del ERP; el usuario decidió no capturarlo).
"""
from logistica.inventario.models import GRADOS
from logistica.inventario.pivote import agrupar_materiales
from logistica.inventario.views import _generar_excel

COLUMNAS = (['Fecha de recibido', 'Colegio', 'Código', 'Regional', 'Ejecutivo',
             'Categoría', 'Referencia']
            + [f'{g}°' for g in GRADOS]
            + ['Total', 'Estado', 'Motivo del rechazo', 'Observaciones'])

ANCHOS = ([16, 30, 12, 16, 24, 20, 24] + [6] * len(GRADOS)
          + [10, 12, 30, 34])


def materiales_devueltos(devolucion):
    """Líneas de la devolución pivotadas: una fila por MATERIAL con sus 12
    celdas por grado (el mismo layout con el que se capturaron).

    Suma las cantidades repetidas: nada impide capturar el mismo material en
    dos filas del formulario, y en la hoja debe verse como una sola.

    Requiere las líneas con `select_related`/`prefetch` de item→categoría (las
    properties del material la leen).
    """
    cantidades, items = {}, {}
    for linea in devolucion.lineas.all():
        cantidades[linea.item_id] = cantidades.get(linea.item_id, 0) + linea.cantidad
        items[linea.item_id] = linea.item
    ordenados = sorted(items.values(),
                       key=lambda i: (i.categoria.nombre, i.referencia, i.grado))
    return agrupar_materiales(ordenados, cantidad=lambda item: cantidades[item.pk])


def filas_detalle(devoluciones):
    """Una fila por (devolución, material) con sus celdas por grado.

    Cada fila lleva la devolución completa, así la tabla en pantalla puede
    pintar cabecera + material sin volver a consultar nada.
    """
    filas = []
    for dev in devoluciones:
        for material in materiales_devueltos(dev):
            filas.append({'devolucion': dev, **material})
    return filas


def filas_export(devoluciones):
    """Filas del Excel: una por (devolución, material)."""
    filas = []
    for fila in filas_detalle(devoluciones):
        dev = fila['devolucion']
        filas.append([
            dev.fecha_recibido.strftime('%d/%m/%Y'), dev.colegio,
            dev.codigo_colegio, dev.regional, dev.ejecutivo,
            fila['categoria'].nombre, fila['referencia'],
            # Celda vacía (no 0) en los grados que no se devolvieron: la
            # hoja distingue "no vino" de "vino en 0".
            *[c['cantidad'] if c['item'] else '' for c in fila['celdas']],
            fila['total'], dev.estado_label, dev.motivo_no_valida,
            dev.observaciones,
        ])
    return filas


def generar_excel_devoluciones(devoluciones):
    """Bytes del .xlsx con el layout de la hoja del usuario."""
    return _generar_excel(titulo='Devoluciones', columnas=COLUMNAS,
                          filas=filas_export(devoluciones), anchos=ANCHOS)
