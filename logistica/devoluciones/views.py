"""Devoluciones de colegios: material despachado que vuelve sin usar.

Sub-app de UI **sin modelos propios**: el dominio (`DevolucionColegio` y su
servicio) vive en `logistica.inventario`, porque toda escritura al stock/ledger
debe pasar por sus servicios transaccionales.
"""
from django.contrib import messages
from django.db import models
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from logistica.despachos.models import OrdenDespacho
from logistica.inventario.forms import parsear_lineas_material
from logistica.inventario.models import GRADOS, DevolucionColegio
from logistica.inventario.permisos import solo_logistica
from logistica.inventario.services import registrar_devolucion_colegio
from logistica.inventario.views import (_fecha_post, _form_a_messages,
                                        _lineas_previas_material,
                                        _materiales_para_lineas,
                                        _respuesta_xlsx)

from .export import generar_excel_devoluciones, materiales_devueltos
from .forms import DevolucionColegioForm


def _devoluciones():
    return (DevolucionColegio.objects.select_related('bodega', 'creado_por')
            .annotate(n_materiales=models.Count('lineas', distinct=True),
                      unidades=Coalesce(models.Sum('lineas__cantidad'), 0)))


def _colegios_erp():
    """Nombres de colegio que ya conoce el ERP de despachos, para autocompletar.

    Mismo criterio que `OrdenDespacho.colegio_erp` (centro de costos y, si viene
    vacío, el cliente). Es solo una ayuda: el campo acepta texto libre.
    """
    pares = (OrdenDespacho.objects.values_list('centro_costos', 'cliente')
             .distinct())
    nombres = {(cc or cl).strip() for cc, cl in pares if (cc or cl).strip()}
    return sorted(nombres)


@solo_logistica
def lista(request):
    return render(request, 'devoluciones/lista.html', {
        'devoluciones': _devoluciones(),
    })


@solo_logistica
def nueva(request):
    """Alta con el mismo patrón que los documentos del inventario: cabecera por
    form, líneas por `parsear_lineas_material` (un material con sus 12 grados) y
    el documento SIEMPRE creado por el servicio (atómico)."""
    form = DevolucionColegioForm(request.POST or None)
    if request.method == 'POST':
        try:
            if not form.is_valid():
                _form_a_messages(request, form)
                raise ValueError('')  # cae al re-render conservando las líneas
            lineas = parsear_lineas_material(request.POST)
            datos = form.cleaned_data
            devolucion = registrar_devolucion_colegio(
                bodega=datos['bodega'], lineas=lineas, usuario=request.user,
                fecha_recibido=datos['fecha_recibido'], colegio=datos['colegio'],
                codigo_colegio=datos['codigo_colegio'],
                regional=datos['regional'], ejecutivo=datos['ejecutivo'],
                observaciones=datos['observaciones'])
        except ValueError as e:
            if str(e):
                messages.error(request, str(e))
        else:
            messages.success(
                request, f'Devolución #{devolucion.pk} registrada: el material '
                         f'ya está sumado a "{devolucion.bodega.nombre}".')
            return redirect('log_devoluciones_detalle', pk=devolucion.pk)
    return render(request, 'devoluciones/form.html', {
        'form': form,
        'materiales': _materiales_para_lineas(),
        'grados': GRADOS,
        'colegios_erp': _colegios_erp(),
        'lineas_previas': _lineas_previas_material(
            request.POST if request.method == 'POST' else None),
    })


@solo_logistica
def detalle(request, pk):
    devolucion = get_object_or_404(
        DevolucionColegio.objects.select_related('bodega', 'creado_por')
        .prefetch_related('lineas__item__categoria'), pk=pk)
    return render(request, 'devoluciones/detalle.html', {
        'devolucion': devolucion,
        'materiales': materiales_devueltos(devolucion),
        'grados': GRADOS,
    })


@require_POST
@solo_logistica
def exportar(request):
    """Excel con el layout de la hoja del usuario (una fila por devolución y
    material). Filtros opcionales de rango de fecha de recibido y colegio."""
    qs = (DevolucionColegio.objects.select_related('bodega')
          .prefetch_related('lineas__item__categoria')
          .order_by('fecha_recibido', 'id'))
    desde, hasta = _fecha_post(request, 'desde'), _fecha_post(request, 'hasta')
    if desde:
        qs = qs.filter(fecha_recibido__gte=desde)
    if hasta:
        qs = qs.filter(fecha_recibido__lte=hasta)
    colegio = (request.POST.get('colegio') or '').strip()
    if colegio:
        qs = qs.filter(colegio__icontains=colegio)

    hoy = timezone.localdate().strftime('%Y%m%d')
    return _respuesta_xlsx(generar_excel_devoluciones(qs),
                           f'Devoluciones_{hoy}.xlsx')
