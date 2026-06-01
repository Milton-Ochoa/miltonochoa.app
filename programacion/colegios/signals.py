"""
Signals de invalidación de caché de auditoría.

Cuando cambia cualquier dato de programación (Clase o Asignacion), la última
sincronización de alertas queda obsoleta. Este signal borra la marca de
tiempo que usa auditoria/engine.py como throttle, forzando una nueva
ejecución de sincronizar() en la próxima visita a la vista de auditoría.

IMPORTANTE: La clave 'auditoria_ultima_sync' debe coincidir exactamente con
la constante _CACHE_KEY definida en auditoria/engine.py. Si se cambia en un
lado, hay que cambiarla en ambos o la invalidación dejará de funcionar.
"""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache

from .models import Clase, Asignacion


@receiver(post_save, sender=Clase)
@receiver(post_delete, sender=Clase)
@receiver(post_save, sender=Asignacion)
@receiver(post_delete, sender=Asignacion)
def _invalidar_auditoria(**kwargs):
    cache.delete('auditoria_ultima_sync')


@receiver(post_save, sender=Clase)
@receiver(post_delete, sender=Clase)
@receiver(post_save, sender=Asignacion)
@receiver(post_delete, sender=Asignacion)
def _invalidar_vista_general(**kwargs):
    # Importación local para evitar circular import (core → colegios → core).
    from core.views import invalidar_vista_general
    invalidar_vista_general()
