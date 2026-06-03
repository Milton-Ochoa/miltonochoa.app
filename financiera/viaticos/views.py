"""Vistas del área **financiera** para la gestión de solicitudes de viáticos.

Financiera **no crea** solicitudes (eso es programación): aquí se **ven** y se
**gestionan** las que llegan. Acciones, según la matriz de permisos:

  - ENVIADA  → devolver (con motivo) / aprobar / editar
  - DEVUELTA → financiera NO actúa (vuelve a programación para corregir y reenviar)
  - APROBADA → editar / pagar
  - PAGADA   → terminal, solo lectura para todos

Los modelos viven en `programacion.viaticos` (BD única); esta app solo los importa.
Se reutiliza el form, el parseo de gastos y el contexto del select-autorrelleno de
programación para no duplicar lógica (mismo widget de filas de gastos en la plantilla).

Gate: superusuario o miembro del grupo `area:financiera`
(`core.areas.es_personal_financiera`). El middleware filtra el acceso al subdominio;
el decorador es la segunda barrera por-vista.
"""
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.areas import es_personal_financiera
from programacion.viaticos.forms import SolicitudViaticoForm
from programacion.viaticos.models import GastoViatico, SolicitudViatico
from programacion.viaticos.views import _contexto_form, _parsear_gastos

solo_financiera = user_passes_test(es_personal_financiera, login_url='login')

# Estados en los que financiera puede editar la solicitud (campos + gastos).
# DEVUELTA queda fuera a propósito: pertenece a programación hasta que la reenvíe;
# PAGADA es terminal. (Ver matriz de permisos arriba.)
EDITABLES_FINANCIERA = {SolicitudViatico.Estado.ENVIADA, SolicitudViatico.Estado.APROBADA}


@solo_financiera
def fin_home(request):
    """Inicio del área financiera (vacío por ahora)."""
    return render(request, 'financiera/home.html')


@solo_financiera
def fin_viaticos_lista(request):
    """Tabla de todas las solicitudes. Las `ENVIADA` son las pendientes de gestión."""
    solicitudes = (
        SolicitudViatico.objects
        .select_related('profesor', 'colegio')
        .prefetch_related('gastos')
    )
    return render(request, 'financiera/viaticos_lista.html', {'solicitudes': solicitudes})


@solo_financiera
def fin_viaticos_detalle(request, pk):
    """Detalle con gastos, total, observaciones y los datos snapshot del docente/colegio.
    Expone qué acciones permite el estado actual para pintar los botones."""
    solicitud = get_object_or_404(
        SolicitudViatico.objects.select_related('profesor', 'colegio').prefetch_related('gastos'),
        pk=pk,
    )
    return render(request, 'financiera/viaticos_detalle.html', {
        'solicitud': solicitud,
        'puede_editar': solicitud.estado in EDITABLES_FINANCIERA,
        'puede_devolver': solicitud.estado == SolicitudViatico.Estado.ENVIADA,
        'puede_aprobar': solicitud.estado == SolicitudViatico.Estado.ENVIADA,
        'puede_pagar': solicitud.estado == SolicitudViatico.Estado.APROBADA,
    })


@solo_financiera
def fin_viaticos_editar(request, pk):
    """Reedita una solicitud `ENVIADA`/`APROBADA` (campos + gastos). No cambia el estado
    ni el snapshot del cliente: el servidor recalcula el snapshot desde la FK."""
    solicitud = get_object_or_404(SolicitudViatico, pk=pk)
    if solicitud.estado not in EDITABLES_FINANCIERA:
        messages.error(request, 'Esta solicitud no se puede editar en su estado actual.')
        return redirect('fin_viaticos_detalle', pk=solicitud.pk)

    if request.method == 'POST':
        form = SolicitudViaticoForm(request.POST, instance=solicitud)
        gastos, errores_gastos = _parsear_gastos(request)
        for e in errores_gastos:
            messages.error(request, e)

        if form.is_valid() and not errores_gastos:
            with transaction.atomic():
                solicitud = form.save(commit=False)
                solicitud.aplicar_snapshot()
                solicitud.save()
                # Reemplazo total de gastos (igual que en programación).
                solicitud.gastos.all().delete()
                GastoViatico.objects.bulk_create(
                    GastoViatico(solicitud=solicitud, **g) for g in gastos
                )
            messages.success(request, 'Solicitud actualizada.')
            return redirect('fin_viaticos_detalle', pk=solicitud.pk)

        return render(request, 'financiera/viaticos_form.html',
                      {**_contexto_form(form, gastos), 'solicitud': solicitud})

    form = SolicitudViaticoForm(instance=solicitud)
    return render(request, 'financiera/viaticos_form.html',
                  {**_contexto_form(form, list(solicitud.gastos.all())), 'solicitud': solicitud})


@solo_financiera
@require_POST
def fin_viaticos_devolver(request, pk):
    """`ENVIADA → DEVUELTA` con un motivo obligatorio (vuelve a programación)."""
    solicitud = get_object_or_404(SolicitudViatico, pk=pk)
    motivo = request.POST.get('motivo_devolucion', '').strip()
    if solicitud.estado != SolicitudViatico.Estado.ENVIADA:
        messages.error(request, 'Solo se puede devolver una solicitud enviada.')
    elif not motivo:
        messages.error(request, 'Indica el motivo de la devolución.')
    else:
        solicitud.estado = SolicitudViatico.Estado.DEVUELTA
        solicitud.motivo_devolucion = motivo
        solicitud.devuelto_en = timezone.now()
        solicitud.gestionado_por = request.user
        solicitud.save()
        messages.success(request, 'Solicitud devuelta a programación.')
    return redirect('fin_viaticos_detalle', pk=solicitud.pk)


@solo_financiera
@require_POST
def fin_viaticos_aprobar(request, pk):
    """`ENVIADA → APROBADA`."""
    solicitud = get_object_or_404(SolicitudViatico, pk=pk)
    if solicitud.estado != SolicitudViatico.Estado.ENVIADA:
        messages.error(request, 'Solo se puede aprobar una solicitud enviada.')
    else:
        solicitud.estado = SolicitudViatico.Estado.APROBADA
        solicitud.aprobado_en = timezone.now()
        solicitud.gestionado_por = request.user
        solicitud.save()
        messages.success(request, 'Solicitud aprobada.')
    return redirect('fin_viaticos_detalle', pk=solicitud.pk)


@solo_financiera
@require_POST
def fin_viaticos_pagar(request, pk):
    """`APROBADA → PAGADA` (estado terminal)."""
    solicitud = get_object_or_404(SolicitudViatico, pk=pk)
    if solicitud.estado != SolicitudViatico.Estado.APROBADA:
        messages.error(request, 'Solo se puede pagar una solicitud aprobada.')
    else:
        solicitud.estado = SolicitudViatico.Estado.PAGADA
        solicitud.pagado_en = timezone.now()
        solicitud.gestionado_por = request.user
        solicitud.save()
        messages.success(request, 'Solicitud marcada como pagada.')
    return redirect('fin_viaticos_detalle', pk=solicitud.pk)
