from .profesor import ProfesorViewSet
from .colegio import ColegioViewSet, ColegioAnioViewSet
from .clase import ClaseViewSet, ClaseParticularViewSet
from .pago import PagoRealizadoViewSet

__all__ = [
    'ProfesorViewSet',
    'ColegioViewSet',
    'ColegioAnioViewSet',
    'ClaseViewSet',
    'ClaseParticularViewSet',
    'PagoRealizadoViewSet',
]
