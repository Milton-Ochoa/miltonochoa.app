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

# Rangos publicados de Cloudflare (www.cloudflare.com/ips). miltonochoa.app está
# proxied por Cloudflare: para Railway "el cliente" es el nodo de CF, así que la IP
# real del usuario solo viaja en CF-Connecting-IP. Ese header únicamente se cree si
# el primer XFF (puesto por Railway = quien se conectó de verdad a su edge, no
# falsificable) cae en estos rangos; si alguien llega directo a Railway con un
# CF-Connecting-IP inventado, se ignora y cuenta por su IP real.
_RANGOS_CLOUDFLARE = [ipaddress.ip_network(r) for r in (
    '173.245.48.0/20', '103.21.244.0/22', '103.22.200.0/22', '103.31.4.0/22',
    '141.101.64.0/18', '108.162.192.0/18', '190.93.240.0/20', '188.114.96.0/20',
    '197.234.240.0/22', '198.41.128.0/17', '162.158.0.0/15', '104.16.0.0/13',
    '104.24.0.0/14', '172.64.0.0/13', '131.0.72.0/22',
    '2400:cb00::/32', '2606:4700::/32', '2803:f800::/32', '2405:b500::/32',
    '2405:8100::/32', '2a06:98c0::/29', '2c0f:f248::/32',
)]


def _es_proxy_confiable(remote_addr: str) -> bool:
    """Verdadero si REMOTE_ADDR es una IP privada o CGNAT, indicando un proxy de
    confianza (Render usa rango privado; Railway usa 100.64.0.0/10)."""
    try:
        ip = ipaddress.ip_address(remote_addr)
        return ip.is_private or (ip.version == 4 and ip in _RANGO_CGNAT)
    except ValueError:
        return False


def _es_ip_cloudflare(ip: 'ipaddress.IPv4Address | ipaddress.IPv6Address') -> bool:
    return any(ip in rango for rango in _RANGOS_CLOUDFLARE)


def _ip_cliente(request) -> str:
    """Resuelve la IP real del cliente detrás de la cadena Cloudflare → Railway.

    Anclaje de confianza: Railway DESCARTA el XFF entrante y lo reconstruye, así que
    el primer valor siempre es quien abrió la conexión contra su edge (verificado
    empíricamente en prod). Si ese peer es Cloudflare, el usuario real está en
    CF-Connecting-IP (CF lo sobrescribe siempre, el cliente no puede inyectarlo)."""
    remote_addr = request.META.get('REMOTE_ADDR', 'unknown')
    if not _es_proxy_confiable(remote_addr):
        return remote_addr

    primera = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
    try:
        peer = ipaddress.ip_address(primera)
    except ValueError:
        return remote_addr

    if _es_ip_cloudflare(peer):
        try:
            return str(ipaddress.ip_address(request.META.get('HTTP_CF_CONNECTING_IP', '').strip()))
        except ValueError:
            pass  # vino por CF pero sin header utilizable: cuenta por el nodo CF
    return str(peer)


def rate_limit(max_calls: int = 60, periodo: int = 60, respuesta: str = 'json'):
    """`respuesta='html'` para vistas que renderizan formularios (login, admin):
    un navegador mostraría el JSON crudo del 429."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            ip = _ip_cliente(request)

            key = f'rl:{view_func.__name__}:{ip}'
            # cache.add es atómico: inicializa el contador solo si la clave no existe.
            cache.add(key, 0, timeout=periodo)
            try:
                contador = cache.incr(key)
            except ValueError:
                # Carrera con el TTL en Redis: la clave puede expirar entre el add
                # y el incr (son dos round-trips de red). Se repone el contador en
                # vez de propagar un 500. NO usar incr(ignore_key_check=True): crea
                # la clave SIN TTL y el contador jamás se resetearía.
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
