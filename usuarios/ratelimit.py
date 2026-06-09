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


# Railway entrega las requests desde el espacio CGNAT (100.64.0.0/10), que ipaddress
# NO considera privado (is_private=False) — sin esto el rate limit ignoraba el XFF y
# contaba a TODOS los usuarios bajo la IP del proxy (límite global compartido).
_RANGO_CGNAT = ipaddress.ip_network('100.64.0.0/10')


def _es_proxy_confiable(remote_addr: str) -> bool:
    """Verdadero si REMOTE_ADDR es una IP privada o CGNAT, indicando un proxy de
    confianza (Render usa rango privado; Railway usa 100.64.0.0/10)."""
    try:
        ip = ipaddress.ip_address(remote_addr)
        return ip.is_private or (ip.version == 4 and ip in _RANGO_CGNAT)
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
                # Railway tiene DOS rutas de tráfico (directa y vía su capa CDN, que añade
                # su POP al final del XFF): el último valor sería el POP regional → todos
                # los usuarios de una región compartirían contador. Railway garantiza que
                # el PRIMER valor es siempre el cliente real (su edge controla el header),
                # consistente en ambas rutas. Si no parsea como IP (cadena manipulada sin
                # pasar por el edge), caemos a remote_addr: solo agrupa a quien manda
                # basura, nunca a clientes legítimos.
                xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
                primera = xff.split(',')[0].strip()
                try:
                    ip = str(ipaddress.ip_address(primera))
                except ValueError:
                    ip = remote_addr
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
