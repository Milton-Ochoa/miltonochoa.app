"""Gate común de las vistas del área logística.

Espejo de `solo_financiera` (financiera.viaticos.views): superusuario o miembro
del grupo 'area:logistica'. El middleware ya bloquea el subdominio a otros roles;
el decorador es la segunda barrera (defensa en profundidad, igual que en las
demás áreas).
"""
from django.contrib.auth.decorators import user_passes_test

from core.areas import es_personal_logistica

solo_logistica = user_passes_test(es_personal_logistica, login_url='login')
