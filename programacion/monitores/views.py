from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.db import transaction
from django.db.models import ProtectedError

from core.areas import es_personal_programacion
from programacion.configuracion.colombia_geo import DEPARTAMENTOS, DEPARTAMENTOS_CIUDADES

from .models import Monitor
from .forms import MonitorForm

# Mismo gate que el resto de Configuración: superusuario o staff del área.
solo_personal = user_passes_test(es_personal_programacion)


@solo_personal
def configuracion_monitores(request):
    """Catálogo de monitores (personas) — CRUD estilo profesores simplificado.

    4 acciones POST: add, edit, toggle_activo, del. Sin historial (a diferencia
    de profesores): el monitor no se audita en HistorialCambio.
    """
    if request.method == 'POST':
        accion = request.POST.get('accion', 'add')

        if accion == 'edit':
            m    = get_object_or_404(Monitor, id=request.POST.get('monitor_id'))
            form = MonitorForm(request.POST, instance=m)
            if form.is_valid():
                form.save()
                messages.success(request, 'Monitor actualizado.')
            else:
                messages.error(request, 'No se pudo guardar: revisa los datos (¿documento duplicado?).')

        elif accion == 'toggle_activo':
            m = get_object_or_404(Monitor, id=request.POST.get('monitor_id'))
            m.activo = not m.activo
            m.save(update_fields=['activo'])

        elif accion == 'del':
            m_del = Monitor.objects.filter(id=request.POST.get('monitor_id')).first()
            if m_del:
                try:
                    m_del.delete()
                    messages.success(request, 'Monitor eliminado.')
                except ProtectedError:
                    # En fases futuras los pagos/asignaciones usarán PROTECT.
                    messages.error(
                        request,
                        'No se puede eliminar el monitor: tiene simulacros o pagos asociados.'
                    )

        else:  # add
            form = MonitorForm(request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, 'Monitor creado.')
            else:
                messages.error(request, 'No se pudo crear: revisa los datos (¿documento duplicado?).')

        return redirect('configuracion_monitores')

    monitores = Monitor.objects.order_by('nombre')

    form_choices = {
        'banco':       Monitor.Banco.choices,
        'tipo_cuenta': Monitor.TipoCuenta.choices,
    }

    return render(request, 'monitores/configuracion_monitores.html', {
        'monitores':          monitores,
        'form_choices':       form_choices,
        'departamentos':      DEPARTAMENTOS,
        'departamentos_json': DEPARTAMENTOS_CIUDADES,
    })
