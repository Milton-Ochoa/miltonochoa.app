"""Gate común de las vistas de personalización.

Idéntico a `logistica.inventario.permisos`: superusuario o miembro del grupo
'area:logistica'. El middleware ya bloquea el subdominio a otros roles; el
decorador es la segunda barrera (defensa en profundidad).
"""
from django.contrib.auth.decorators import user_passes_test

from core.areas import es_personal_logistica

solo_logistica = user_passes_test(es_personal_logistica, login_url='login')
