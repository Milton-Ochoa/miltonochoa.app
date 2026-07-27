"""Servicios de dominio del inventario.

ÚNICA puerta de escritura a `Stock` y `Movimiento`: las vistas (y cualquier
otro código) NUNCA los tocan directo. Cada operación es `transaction.atomic`
— si una línea falla (p. ej. stock insuficiente), NADA queda escrito: ni el
documento ni los movimientos de las líneas anteriores.

Concurrencia: el stock se lee con `select_for_update`, así dos escrituras
simultáneas sobre el mismo (item, bodega) se serializan en PostgreSQL.
OJO: `select_for_update` es un no-op en SQLite (dev local y tests) — ahí la
atomicidad SÍ se prueba (rollback), pero la exclusión real solo existe en
producción. Como última barrera, `Stock.cantidad` es PositiveIntegerField
(CHECK >= 0 en BD): una carrera jamás deja saldo negativo, explota.
"""
from django.db import models, transaction
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import (Devolucion, Entrada, EntradaLinea, Item, Movimiento,
                     Prestamo, PrestamoLinea, Salida, SalidaLinea, Stock,
                     Traslado, TrasladoLinea)


class StockInsuficiente(Exception):
    """No hay existencias para cubrir la operación. Las vistas la traducen a
    `messages.error`; el atomic que la deja escapar revierte todo."""

    def __init__(self, item, bodega, disponible, solicitado):
        self.item = item
        self.bodega = bodega
        self.disponible = disponible
        self.solicitado = solicitado
        super().__init__(
            f'Stock insuficiente de "{item.nombre}" en "{bodega.nombre}": '
            f'hay {disponible}, se solicitaron {solicitado}.'
        )


class ErrorDevolucion(Exception):
    """Devolución inválida (préstamo cerrado, cantidad 0 o mayor al pendiente,
    línea de otro préstamo…)."""


def _stock_bloqueado(item, bodega):
    """Fila de Stock de (item, bodega) con lock de fila tomado.

    `get_or_create` primero (la fila puede no existir aún) y re-SELECT con
    `select_for_update` después: el lock solo vale si se toma en el SELECT.
    """
    Stock.objects.get_or_create(item=item, bodega=bodega)
    return Stock.objects.select_for_update().get(item=item, bodega=bodega)


def _aplicar_movimiento(*, item, bodega, tipo, cantidad, usuario, detalle='',
                        entrada=None, salida=None, prestamo=None,
                        devolucion=None, traslado=None):
    """Núcleo privado: aplica un movimiento al stock y lo asienta en el ledger.

    Valida cantidad > 0 y no-negativos, actualiza Stock con expresión F()
    (atómico en SQL) y crea el `Movimiento` con su `saldo_resultante`
    calculado bajo el lock. Debe llamarse dentro de un atomic.
    """
    if cantidad <= 0:
        raise ValueError('La cantidad debe ser mayor que cero.')

    stock = _stock_bloqueado(item, bodega)
    delta = cantidad if tipo in Movimiento.TIPOS_POSITIVOS else -cantidad
    nuevo_saldo = stock.cantidad + delta
    if nuevo_saldo < 0:
        raise StockInsuficiente(item, bodega, stock.cantidad, cantidad)

    Stock.objects.filter(pk=stock.pk).update(
        cantidad=models.F('cantidad') + delta)
    return Movimiento.objects.create(
        item=item, bodega=bodega, tipo=tipo, cantidad=cantidad,
        saldo_resultante=nuevo_saldo, detalle=detalle[:250], creado_por=usuario,
        entrada=entrada, salida=salida, prestamo=prestamo,
        devolucion=devolucion, traslado=traslado,
    )


# ---------------------------------------------------------------------------
# Operaciones
# ---------------------------------------------------------------------------

@transaction.atomic
def registrar_entrada(*, bodega, lineas, usuario, proveedor='',
                      observaciones=''):
    """Entrada de mercancía a una bodega. ``lineas`` = [(Item, cantidad)]."""
    if not lineas:
        raise ValueError('La entrada necesita al menos una línea.')
    entrada = Entrada.objects.create(bodega=bodega, proveedor=proveedor,
                                     observaciones=observaciones,
                                     creado_por=usuario)
    detalle = f'Entrada #{entrada.pk}' + (f' — {proveedor}' if proveedor else '')
    for item, cantidad in lineas:
        # El movimiento va primero: valida cantidad/stock y lanza la excepción
        # de dominio antes de que el CHECK de BD de la línea convierta el error
        # en un IntegrityError críptico.
        _aplicar_movimiento(item=item, bodega=bodega,
                            tipo=Movimiento.Tipo.ENTRADA, cantidad=cantidad,
                            usuario=usuario, detalle=detalle, entrada=entrada)
        EntradaLinea.objects.create(entrada=entrada, item=item, cantidad=cantidad)
    return entrada


@transaction.atomic
def registrar_salida(*, bodega, lineas, usuario, tercero=None,
                     tercero_nombre='', motivo='', observaciones=''):
    """Salida definitiva de una bodega. ``lineas`` = [(Item, cantidad)].

    Lanza `StockInsuficiente` (y revierte todo) si alguna línea no alcanza.
    """
    if not lineas:
        raise ValueError('La salida necesita al menos una línea.')
    if tercero is not None and not tercero_nombre:
        tercero_nombre = tercero.nombre
    salida = Salida.objects.create(bodega=bodega, tercero=tercero,
                                   tercero_nombre=tercero_nombre, motivo=motivo,
                                   observaciones=observaciones,
                                   creado_por=usuario)
    detalle = f'Salida #{salida.pk}'
    if tercero_nombre:
        detalle += f' — {tercero_nombre}'
    if motivo:
        detalle += f' ({motivo})'
    for item, cantidad in lineas:
        _aplicar_movimiento(item=item, bodega=bodega,
                            tipo=Movimiento.Tipo.SALIDA, cantidad=cantidad,
                            usuario=usuario, detalle=detalle, salida=salida)
        SalidaLinea.objects.create(salida=salida, item=item, cantidad=cantidad)
    return salida


@transaction.atomic
def registrar_traslado(*, bodega_origen, bodega_destino, lineas, usuario,
                       observaciones=''):
    """Traslado atómico entre bodegas: por cada línea, TRASLADO_SAL en origen
    + TRASLADO_ENT en destino dentro del mismo atomic."""
    if not lineas:
        raise ValueError('El traslado necesita al menos una línea.')
    if bodega_origen == bodega_destino:
        raise ValueError('La bodega de origen y la de destino deben ser distintas.')
    traslado = Traslado.objects.create(bodega_origen=bodega_origen,
                                       bodega_destino=bodega_destino,
                                       observaciones=observaciones,
                                       creado_por=usuario)
    detalle = (f'Traslado #{traslado.pk} — {bodega_origen.nombre} → '
               f'{bodega_destino.nombre}')
    for item, cantidad in lineas:
        _aplicar_movimiento(item=item, bodega=bodega_origen,
                            tipo=Movimiento.Tipo.TRASLADO_SAL,
                            cantidad=cantidad, usuario=usuario,
                            detalle=detalle, traslado=traslado)
        _aplicar_movimiento(item=item, bodega=bodega_destino,
                            tipo=Movimiento.Tipo.TRASLADO_ENT,
                            cantidad=cantidad, usuario=usuario,
                            detalle=detalle, traslado=traslado)
        TrasladoLinea.objects.create(traslado=traslado, item=item,
                                     cantidad=cantidad)
    return traslado


@transaction.atomic
def crear_prestamo(*, tercero, fecha_compromiso, lineas, usuario,
                   direccion=Prestamo.Direccion.OTORGADO, observaciones=''):
    """Préstamo en cualquier dirección. ``lineas`` = [(Item, Bodega, cantidad)].

    OTORGADO: movimiento PRESTAMO por línea (descuenta, valida stock).
    RECIBIDO: movimiento PREST_RECIBIDO (suma, sin validación — nos prestan).
    """
    if not lineas:
        raise ValueError('El préstamo necesita al menos una línea.')
    prestamo = Prestamo.objects.create(
        direccion=direccion, tercero=tercero,
        tercero_nombre=tercero.nombre, tercero_documento=tercero.documento,
        fecha_compromiso=fecha_compromiso, observaciones=observaciones,
        creado_por=usuario,
    )
    otorgado = direccion == Prestamo.Direccion.OTORGADO
    tipo = Movimiento.Tipo.PRESTAMO if otorgado else Movimiento.Tipo.PREST_RECIBIDO
    detalle = (f'Préstamo #{prestamo.pk} '
               f'({"a" if otorgado else "de"} {prestamo.tercero_nombre})')
    for item, bodega, cantidad in lineas:
        _aplicar_movimiento(item=item, bodega=bodega, tipo=tipo,
                            cantidad=cantidad, usuario=usuario,
                            detalle=detalle, prestamo=prestamo)
        PrestamoLinea.objects.create(prestamo=prestamo, item=item,
                                     bodega=bodega,
                                     cantidad_prestada=cantidad)
    return prestamo


@transaction.atomic
def registrar_devolucion(*, prestamo, lineas, usuario, observaciones=''):
    """Devolución (parcial o total) de un préstamo.
    ``lineas`` = [(PrestamoLinea, cantidad)].

    Opera sobre la bodega de cada línea prestada. Según la dirección:
    OTORGADO → DEVOLUCION suma a esa bodega; RECIBIDO → DEV_RECIBIDO descuenta
    de ella (con validación `StockInsuficiente`). Recalcula el estado del
    préstamo (PARCIAL/CERRADO) al final.
    """
    if prestamo.estado == Prestamo.Estado.CERRADO:
        raise ErrorDevolucion('El préstamo ya está cerrado.')
    if not lineas:
        raise ErrorDevolucion('La devolución necesita al menos una línea.')

    otorgado = prestamo.direccion == Prestamo.Direccion.OTORGADO
    tipo = Movimiento.Tipo.DEVOLUCION if otorgado else Movimiento.Tipo.DEV_RECIBIDO
    devolucion = Devolucion.objects.create(prestamo=prestamo,
                                           observaciones=observaciones,
                                           creado_por=usuario)
    detalle = f'Devolución de préstamo #{prestamo.pk} ({prestamo.tercero_nombre})'
    for linea, cantidad in lineas:
        if linea.prestamo_id != prestamo.pk:
            raise ErrorDevolucion('La línea no pertenece a este préstamo.')
        if cantidad <= 0:
            raise ErrorDevolucion('La cantidad a devolver debe ser mayor que cero.')
        if cantidad > linea.pendiente:
            raise ErrorDevolucion(
                f'Se intentan devolver {cantidad} de "{linea.item.nombre}" '
                f'pero solo hay {linea.pendiente} pendientes.')
        _aplicar_movimiento(item=linea.item, bodega=linea.bodega, tipo=tipo,
                            cantidad=cantidad, usuario=usuario,
                            detalle=detalle, prestamo=prestamo,
                            devolucion=devolucion)
        PrestamoLinea.objects.filter(pk=linea.pk).update(
            cantidad_devuelta=models.F('cantidad_devuelta') + cantidad)

    # Estado desde la BD (las líneas en memoria pueden estar desactualizadas).
    pendientes = (PrestamoLinea.objects.filter(prestamo=prestamo)
                  .aggregate(p=models.Sum(models.F('cantidad_prestada')
                                          - models.F('cantidad_devuelta')))['p'])
    if pendientes == 0:
        prestamo.estado = Prestamo.Estado.CERRADO
        prestamo.cerrado_en = timezone.now()
    else:
        prestamo.estado = Prestamo.Estado.PARCIAL
    prestamo.save(update_fields=['estado', 'cerrado_en'])
    return devolucion


@transaction.atomic
def registrar_ajuste(*, item, bodega, nueva_cantidad, usuario, motivo):
    """Ajuste manual del stock de (item, bodega) a un valor absoluto.

    El motivo es OBLIGATORIO (queda en el ledger). Si la cantidad no cambia,
    ValueError: un ajuste sin delta no deja rastro útil.
    """
    if not (motivo or '').strip():
        raise ValueError('El ajuste requiere un motivo.')
    if nueva_cantidad < 0:
        raise ValueError('La cantidad ajustada no puede ser negativa.')

    stock = _stock_bloqueado(item, bodega)
    delta = nueva_cantidad - stock.cantidad
    if delta == 0:
        raise ValueError('La cantidad no cambia: no hay nada que ajustar.')
    tipo = (Movimiento.Tipo.AJUSTE_POS if delta > 0
            else Movimiento.Tipo.AJUSTE_NEG)
    return _aplicar_movimiento(item=item, bodega=bodega, tipo=tipo,
                               cantidad=abs(delta), usuario=usuario,
                               detalle=f'Ajuste: {motivo.strip()}')


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------

def kardex(item, *, bodega=None, desde=None, hasta=None):
    """Movimientos de un item en orden cronológico (con `saldo_resultante`
    por fila, listo para pintar el kardex sin window functions)."""
    qs = Movimiento.objects.filter(item=item).select_related('bodega')
    if bodega is not None:
        qs = qs.filter(bodega=bodega)
    if desde is not None:
        qs = qs.filter(creado_en__date__gte=desde)
    if hasta is not None:
        qs = qs.filter(creado_en__date__lte=hasta)
    return qs.order_by('creado_en', 'id')


def items_bajo_minimo():
    """Items activos cuyo stock TOTAL (suma de bodegas) está en o bajo su
    mínimo. `stock_minimo=0` significa "sin alerta" y queda fuera."""
    return (Item.objects.filter(activo=True, stock_minimo__gt=0)
            .select_related('categoria')  # `Item.nombre` lee la categoría
            .annotate(stock_total=Coalesce(models.Sum('stocks__cantidad'), 0))
            .filter(stock_total__lte=models.F('stock_minimo'))
            .order_by('categoria__nombre', 'referencia', 'grado'))


def prestamos_vencidos():
    """Préstamos no cerrados (ambas direcciones) con compromiso vencido."""
    return (Prestamo.objects
            .exclude(estado=Prestamo.Estado.CERRADO)
            .filter(fecha_compromiso__lt=timezone.localdate())
            .order_by('fecha_compromiso'))
