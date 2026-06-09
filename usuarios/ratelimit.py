"""
Decorador de rate-limiting respaldado por el framework de caché de Django.
Uso: @rate_limit(max_calls=30, periodo=60)
"""
import ipaddress
import logging
from functools import wraps
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse

logger = logging.getLogger('aamo')

_MENSAJE_429 = 'Demasiadas solicitudes. Espera un momento.'


def _es_proxy_confiable(remote_addr: str) -> bool:
    """Verdadero si REMOTE_ADDR es una IP privada, indicando un proxy de confianza (p.ej. Render)."""
    try:
        return ipaddress.ip_address(remote_addr).is_private
    except ValueError:
        return False


def rate_limit(max_calls: int = 60, periodo: int = 60, respuesta: str = 'json'):
    """`respuesta='html'` para vistas que renderizan formularios (login, admin):
    un navegador mostraría el JSON crudo del 429."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            remote_addr = request.META.get('REMOTE_ADDR', 'unknown')
            if _es_proxy_confiable(remote_addr):
                # En Render (proxy de un solo salto) tomamos el último XFF,
                # que fue añadido por el proxy confiable — no es manipulable por el cliente.
                xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
                ip = xff.split(',')[-1].strip() or remote_addr
            else:
                ip = remote_addr

            key = f'rl:{view_func.__name__}:{ip}'
            # cache.add es atómico: inicializa el contador solo si la clave no existe.
            cache.add(key, 0, timeout=periodo)
            contador = cache.incr(key)

            if contador > max_calls:
                logger.warning('Rate limit superado: %s desde %s', view_func.__name__, ip)
                if respuesta == 'html':
                    return HttpResponse(
                        f'<h1>429</h1><p>{_MENSAJE_429}</p>',
                        status=429, content_type='text/html; charset=utf-8',
                    )
                return JsonResponse({'error': _MENSAJE_429}, status=429)
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator
