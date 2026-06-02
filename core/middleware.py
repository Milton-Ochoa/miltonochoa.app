"""Enrutado por subdominio (área) para AAMO.

Cada área se sirve en su propio subdominio. Este middleware mira el host de la
petición y, si corresponde a un área registrada, fija `request.urlconf` al
urlconf de esa área (que se monta en la raíz del subdominio) y deja
`request.area = '<slug>'`. El apex (`miltonochoa.app`/`www`) usa `ROOT_URLCONF`
(login único + selector de área) y `request.area = None`.

Hosts ajenos al dominio (localhost, IP directa, dominio interno de Railway,
healthchecks) se tratan como apex para no romper despliegues ni sondas.
"""
from django.conf import settings
from django.http import Http404

from core.areas import AREAS


class EnrutadoPorAreaMiddleware:
    """Selecciona el urlconf según el subdominio. Debe ir antes de CommonMiddleware."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.dominio = settings.BASE_DOMAIN
        self.sufijo = '.' + settings.BASE_DOMAIN

    def __call__(self, request):
        host = request.get_host().split(':')[0]
        request.area = None

        if host == self.dominio or host == 'www.' + self.dominio:
            pass  # apex → ROOT_URLCONF
        elif host.endswith(self.sufijo):
            sub = host[:-len(self.sufijo)].split('.')[0]
            area = AREAS.get(sub)
            if area is not None:
                request.urlconf = area['urlconf']
                request.area = sub
            else:
                # Subdominio del dominio pero sin área registrada → 404 controlado.
                raise Http404(f'Área desconocida: {sub}')
        # else: host ajeno al dominio → apex (no rompe healthchecks ni IP directa)

        return self.get_response(request)
