"""Vistas del área **financiera** para los pagos de **monitores** (simulacros).

Espejo exacto de ``financiera.pagos`` pero con **fuente = simulacros**: programación
materializa y revisa las filas ``PagoMonitor`` (grano `(monitor, simulacro)`) en un
``LoteMonitores`` BORRADOR y lo **envía**; financiera **solo ve las filas de lotes
ENVIADO** (guard ``_lote_enviado``) y las **gestiona**: marca/desmarca el pago
(`fecha_pago`/`marcado_por`) y sube/elimina los soportes (comprobantes). Programación
las consulta en solo lectura.

El cálculo y los helpers compartidos (``construir_contexto_monitores``,
``filas_monitores_por_tab``, ``_generar_excel_pagos``) viven en
``programacion.monitores.pagos_views`` y se importan con ``modo='financiera'`` (BD única,
sin duplicar lógica). **Sin** proyección (eso es propio de profesores/clases).

Gate: superusuario o grupo `area:financiera` (`core.areas.es_personal_financiera`).
"""
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.areas import es_personal_financiera
from programacion.monitores.models import (
    LoteMonitores, PagoMonitor, SoportePagoMonitor)
from programacion.monitores.pagos_views import (
    construir_contexto_monitores, filas_monitores_por_tab)
from programacion.pagos.views import _generar_excel_pagos, _label_rango, _parse_fecha
from programacion.viaticos.soportes import validar_soporte
from programacion.viaticos.views import _responder_soporte

solo_financiera = user_passes_test(es_personal_financiera, login_url='login')


def _lote_enviado(pago):
    """Financiera solo ve lo enviado: cualquier acceso a una fila cuyo lote no esté
    ENVIADO (BORRADOR, o histórico sin lote) se rechaza. Mismo guard que el de
    ``financiera.pagos`` para profesores."""
    return pago.lote is not None and pago.lote.estado == LoteMonitores.Estado.ENVIADO


@solo_financiera
def fin_monitores_pagos_lista(request):
    """Tabla de pagos de monitores (tabs pendiente/realizado). Mismo cálculo que
    programación (reutiliza ``construir_contexto_monitores`` con ``modo='financiera'``),
    dibujado en el chrome financiera con las acciones de marcar/soporte."""
    return render(request, 'financiera/pagos_monitores.html',
                  construir_contexto_monitores(request.GET, modo='financiera'))


@solo_financiera
@require_POST
def fin_monitores_pagos_marcar(request):
    """Marca/desmarca una fila enviada como pago realizado, fijando/limpiando `fecha_pago`.

    La fila ya existe (la materializó y envió programación): financiera solo registra el
    pago, no crea filas. Solo se gestiona si pertenece a un lote ENVIADO. `desmarcar`
    limpia `fecha_pago`/`marcado_por` y borra los soportes (archivos en storage + filas),
    pero **conserva la fila** (sigue siendo parte del lote enviado)."""
    try:
        pago_id = int(request.POST.get('pago_id', ''))
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'Datos inválidos'}, status=400)

    pago = get_object_or_404(
        PagoMonitor.objects.select_related('lote').prefetch_related('soportes'),
        pk=pago_id)
    if not _lote_enviado(pago):
        return JsonResponse(
            {'ok': False, 'error': 'El pago no está disponible para financiera.'}, status=400)

    if request.POST.get('accion', 'marcar') == 'desmarcar':
        for soporte in pago.soportes.all():
            soporte.archivo.delete(save=False)
        pago.soportes.all().delete()
        pago.fecha_pago = None
        pago.marcado_por = None
        pago.save(update_fields=['fecha_pago', 'marcado_por'])
        return JsonResponse({'ok': True, 'accion': 'desmarcado', 'id': pago.id})

    pago.fecha_pago = timezone.now()
    pago.marcado_por = request.user
    pago.save(update_fields=['fecha_pago', 'marcado_por'])
    return JsonResponse({'ok': True, 'accion': 'marcado', 'id': pago.id})


@solo_financiera
@require_POST
def fin_monitores_pagos_exportar(request):
    """Descarga el `.xlsx` del tab activo (reusa el generador de programación).

    Rango opcional: si no llega filtro de fecha, se exporta **todo** el backlog del tab
    (no la semana actual), igual que en programación."""
    fi = _parse_fecha(request.POST.get('fecha_inicio', ''))
    ff = _parse_fecha(request.POST.get('fecha_fin', ''))

    tab = request.POST.get('tab', 'pendiente')
    filas = filas_monitores_por_tab(fi, ff, tab, modo='financiera')
    excel_bytes = _generar_excel_pagos(filas, _label_rango(fi, ff))

    sufijo = 'Realizados' if tab == 'realizado' else 'Pendientes'
    label = f"{fi.strftime('%Y%m%d')}_{ff.strftime('%Y%m%d')}" if fi and ff else 'todos'
    response = HttpResponse(
        excel_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="PagosMonitores_{sufijo}_{label}.xlsx"'
    return response


# ══════════════════════════════════════════════════════════════
# DETALLE + SOPORTES (comprobante por pago)
# ══════════════════════════════════════════════════════════════

@solo_financiera
def fin_monitores_pago_detalle(request, pago_id):
    """Detalle de un pago de monitor realizado: datos del monitor/simulacro y gestión de
    soportes (subir/ver/descargar/eliminar). Espejo del detalle de pagos de profesores."""
    pago = get_object_or_404(
        PagoMonitor.objects
        .select_related('monitor', 'simulacro__colegio', 'marcado_por', 'lote', 'lote__enviado_por')
        .prefetch_related('extras', 'soportes', 'soportes__subido_por'),
        pk=pago_id,
    )
    if not _lote_enviado(pago):
        messages.error(request, 'El pago no está disponible para financiera.')
        return redirect('fin_monitores_pagos_lista')
    return render(request, 'financiera/pago_monitor_detalle.html', {'pago': pago})


@solo_financiera
@require_POST
def fin_monitores_pago_subir_soporte(request, pago_id):
    """Adjunta un comprobante a un pago de monitor (mismo validador que viáticos)."""
    pago = get_object_or_404(PagoMonitor.objects.select_related('lote'), pk=pago_id)
    if not _lote_enviado(pago):
        messages.error(request, 'El pago no está disponible para financiera.')
        return redirect('fin_monitores_pagos_lista')
    archivo = request.FILES.get('archivo')
    if not archivo:
        messages.error(request, 'Selecciona un archivo para subir.')
        return redirect('fin_monitores_pago_detalle', pago_id=pago.pk)

    error = validar_soporte(archivo)
    if error:
        messages.error(request, error)
        return redirect('fin_monitores_pago_detalle', pago_id=pago.pk)

    SoportePagoMonitor.objects.create(
        pago=pago, archivo=archivo, nombre_original=archivo.name, subido_por=request.user)
    messages.success(request, 'Soporte de pago adjuntado.')
    return redirect('fin_monitores_pago_detalle', pago_id=pago.pk)


@solo_financiera
@require_POST
def fin_monitores_pago_eliminar_soporte(request, soporte_id):
    """Elimina un soporte (y su archivo en storage) subido por error."""
    soporte = get_object_or_404(
        SoportePagoMonitor.objects.select_related('pago__lote'), pk=soporte_id)
    if not _lote_enviado(soporte.pago):
        messages.error(request, 'El pago no está disponible para financiera.')
        return redirect('fin_monitores_pagos_lista')
    pago_id = soporte.pago_id
    soporte.archivo.delete(save=False)  # primero el storage, luego la fila
    soporte.delete()
    messages.success(request, 'Soporte eliminado.')
    return redirect('fin_monitores_pago_detalle', pago_id=pago_id)


@solo_financiera
def fin_monitores_pago_soporte_descargar(request, soporte_id):
    """Ver (`?inline=1`) o descargar un soporte. Mismo proxy server-side que viáticos."""
    soporte = get_object_or_404(
        SoportePagoMonitor.objects.select_related('pago__lote'), pk=soporte_id)
    if not _lote_enviado(soporte.pago):
        raise Http404
    return _responder_soporte(soporte, inline=request.GET.get('inline') == '1')
