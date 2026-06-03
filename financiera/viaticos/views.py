"""Vistas del área **financiera**.

Fase 3: solo el Inicio (placeholder) y un placeholder de Viáticos, para arrancar el
subdominio con su chrome y menú. La gestión real de viáticos (listar/devolver/
aprobar/pagar, importando `programacion.viaticos.models`) llega en la Fase 4.

Gate: superusuario o miembro del grupo `area:financiera`
(`core.areas.es_personal_financiera`). El middleware ya filtra el acceso al
subdominio; el decorador es la segunda barrera por-vista.
"""
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import render

from core.areas import es_personal_financiera

solo_financiera = user_passes_test(es_personal_financiera, login_url='login')


@solo_financiera
def fin_home(request):
    """Inicio del área financiera (vacío por ahora)."""
    return render(request, 'financiera/home.html')


@solo_financiera
def fin_viaticos_lista(request):
    """Placeholder de viáticos (la gestión real llega en la Fase 4)."""
    return render(request, 'financiera/viaticos_lista.html')
