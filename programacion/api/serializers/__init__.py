from .profesor import ProfesorSerializer
from .colegio import ColegioSerializer, ColegioAnioSerializer
from .clase import ClaseSerializer, ClaseParticularSerializer
from .pago import PagoRealizadoSerializer

__all__ = [
    'ProfesorSerializer',
    'ColegioSerializer',
    'ColegioAnioSerializer',
    'ClaseSerializer',
    'ClaseParticularSerializer',
    'PagoRealizadoSerializer',
]
