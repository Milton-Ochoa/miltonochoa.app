from django import template
from django.core.cache import cache
from django.utils.html import escape
from django.utils.safestring import mark_safe
from programacion.configuracion.models import Materia

register = template.Library()

_CACHE_KEY = 'materia_color_map'
_CACHE_TTL = 10  # segundos


def _color_map():
    """Nombre_lower -> color, con cache de Django."""
    mapa = cache.get(_CACHE_KEY)
    if mapa is None:
        mapa = {
            m.nombre.lower(): m.color
            for m in Materia.objects.only('nombre', 'color')
        }
        cache.set(_CACHE_KEY, mapa, _CACHE_TTL)
    return mapa


@register.simple_tag()
def materia_badge(nombre):
    """Devuelve un badge HTML con el color de la materia."""
    if not nombre:
        return mark_safe('—')
    nombre = str(nombre)
    color = _color_map().get(nombre.lower(), '#6c757d')
    return mark_safe(
        f'<span class="badge rounded-pill" '
        f'style="background-color:{escape(color)}">{escape(nombre)}</span>'
    )


@register.simple_tag()
def materia_color(nombre):
    """Devuelve solo el color hex de la materia."""
    if not nombre:
        return '#6c757d'
    nombre = str(nombre)
    return _color_map().get(nombre.lower(), '#6c757d')


@register.filter
def get_item(dictionary, key):
    """Acceso a diccionario por clave en templates."""
    if not isinstance(dictionary, dict):
        return None
    return dictionary.get(key)


@register.filter
def iniciales(value):
    """Iniciales en mayúscula de cada palabra: "Lectura Crítica" -> "LC"."""
    if not value:
        return ''
    return ''.join(p[0].upper() for p in str(value).split() if p)
