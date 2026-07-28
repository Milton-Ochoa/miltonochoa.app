"""Permisos del área logística: gate de área + restricción por bodega.

Dos capas:

1. `solo_logistica` — gate binario del ÁREA (espejo de `solo_financiera`):
   superusuario o miembro del grupo 'area:logistica'. El middleware ya bloquea
   el subdominio a otros roles; el decorador es la segunda barrera (defensa en
   profundidad, igual que en las demás áreas).

2. **Bodega por usuario** — dentro del área, quien tenga un `BodegaUsuario`
   solo puede ESCRIBIR en su bodega (entradas, salidas, ajustes, préstamos,
   devoluciones y el origen de los traslados). La LECTURA nunca se restringe.

   Reglas, en este orden:
     - sin usuario / anónimo  → sin restricción (inalcanzable tras el gate de
       área, pero no debe reventar si alguien llama al helper suelto)
     - `is_superuser`         → sin restricción, aunque tenga fila
     - sin fila               → sin restricción (comportamiento histórico)
     - con fila               → solo esa bodega

   La restricción NO vive en `services.py` a propósito: el `usuario` que reciben
   los servicios es el actor del ledger (lo llaman tests y podría llamarlos un
   command), las reglas son de caso de uso y no de dominio (origen sí / destino
   no en traslados) y hay escrituras que no pasan por servicios (catálogo de
   bodegas, adjuntos). Se valida en vistas/forms, con el queryset recortado como
   primera barrera y estos helpers como segunda.
"""
from django.contrib.auth.decorators import user_passes_test

from core.areas import es_personal_logistica

from .models import Bodega, BodegaUsuario

solo_logistica = user_passes_test(es_personal_logistica, login_url='login')

_SIN_MEMO = object()


class BodegaNoPermitida(Exception):
    """Escritura sobre una bodega que el usuario no opera.

    Mismo contrato que `StockInsuficiente`/`ErrorDevolucion`: las vistas la
    atrapan y la vuelcan a `messages.error` con el texto tal cual.
    """

    def __init__(self, bodega, asignada, accion='registrar movimientos en'):
        self.bodega = bodega
        self.asignada = asignada
        self.accion = accion
        super().__init__(
            f'No puedes {accion} "{bodega}": tu bodega asignada es '
            f'"{asignada}". Puedes consultarla, pero no escribir en ella.')


def bodega_asignada(user):
    """La `Bodega` asignada al usuario, o None si no tiene.

    Memoiza en el propio objeto `user` porque en una petición de escritura se
    consulta 2-3 veces (form + guard + template). Sin caché de proceso: un
    cambio de asignación aplica al request siguiente, misma postura que
    `resolver_acceso_area`.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return None
    memo = getattr(user, '_bodega_inv_memo', _SIN_MEMO)
    if memo is _SIN_MEMO:
        fila = (BodegaUsuario.objects.select_related('bodega')
                .filter(usuario=user).first())
        memo = fila.bodega if fila else None
        user._bodega_inv_memo = memo
    return memo


def es_restringido(user):
    """True si el usuario solo puede escribir en su bodega."""
    if not user or getattr(user, 'is_superuser', False):
        return False
    return bodega_asignada(user) is not None


def bodegas_escribibles(user):
    """QuerySet de bodegas en las que el usuario puede escribir.

    No filtra por `activa`: eso lo hace quien lo consume, para que un usuario
    con la bodega desactivada vea "tu bodega está inactiva" y no "no puedes
    escribir aquí".
    """
    if not es_restringido(user):
        return Bodega.objects.all()
    return Bodega.objects.filter(pk=bodega_asignada(user).pk)


def puede_escribir_en(user, bodega):
    if not es_restringido(user):
        return True
    return bodega is not None and bodega.pk == bodega_asignada(user).pk


def exigir_bodega(user, bodega, *, accion='registrar movimientos en'):
    """Lanza `BodegaNoPermitida` si el usuario no puede escribir en `bodega`."""
    if not puede_escribir_en(user, bodega):
        raise BodegaNoPermitida(bodega, bodega_asignada(user), accion)


def exigir_bodegas(user, bodegas, *, accion='registrar movimientos en'):
    """Igual que `exigir_bodega` sobre un iterable: lanza en la primera ajena."""
    for bodega in bodegas:
        exigir_bodega(user, bodega, accion=accion)
