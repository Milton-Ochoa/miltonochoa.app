"""Vistas del área **financiera** para los pagos de clases a profesores.

Espejo del flujo de viáticos, pero **sin emails** y con grano por fila
`(profesor, colegio, día)`: el sistema **calcula** (helpers de `programacion.exportar`)
y financiera **gestiona** —marca el pago (PENDIENTE→PAGADA) y, por fila pagada,
sube/elimina los soportes (comprobantes)—. Programación solo ve (solo lectura).

PENDIENTE = no existe `PagoRealizado` para esa fila; PAGADA = existe. Marcar crea el
registro; desmarcar lo borra (y, en cascada, sus soportes; los archivos se limpian del
storage antes para no dejar huérfanos).

Gate: superusuario o grupo `area:financiera` (`core.areas.es_personal_financiera`).
"""
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.areas import es_personal_financiera
from programacion.pagos.models import LotePagos, PagoRealizado, SoportePagoProfesor
from programacion.pagos.views import (
    construir_contexto_pagos, filas_pagos_por_tab,
    _generar_excel_pagos, _label_rango, _parse_fecha,
)
from programacion.viaticos.soportes import validar_soporte
from programacion.viaticos.views import _responder_soporte

solo_financiera = user_passes_test(es_personal_financiera, login_url='login')


@solo_financiera
def fin_pagos_lista(request):
    """Tabla semanal de pagos (tabs pendiente/realizado). Mismo cálculo que
    programación (reutiliza `construir_contexto_pagos`), dibujado en el chrome
    financiera con las acciones de marcar/soporte."""
    return render(request, 'financiera/pagos.html',
                  construir_contexto_pagos(request.GET, modo='financiera'))


@solo_financiera
@require_POST
def fin_pagos_marcar(request):
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
        PagoRealizado.objects.select_related('lote').prefetch_related('soportes'),
        pk=pago_id)
    if not pago.lote or pago.lote.estado != LotePagos.Estado.ENVIADO:
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
def fin_pagos_exportar(request):
    """Descarga el `.xlsx` del tab activo (reusa el generador de programación).

    Rango opcional: si no llega filtro de fecha, se exporta **todo** el backlog del tab
    (no la semana actual), igual que en programación."""
    fi = _parse_fecha(request.POST.get('fecha_inicio', ''))
    ff = _parse_fecha(request.POST.get('fecha_fin', ''))

    tab = request.POST.get('tab', 'pendiente')
    filas = filas_pagos_por_tab(fi, ff, tab, modo='financiera')
    excel_bytes = _generar_excel_pagos(filas, _label_rango(fi, ff))

    sufijo = 'Realizados' if tab == 'realizado' else 'Pendientes'
    label = f"{fi.strftime('%Y%m%d')}_{ff.strftime('%Y%m%d')}" if fi and ff else 'todos'
    response = HttpResponse(
        excel_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="Pagos_{sufijo}_{label}.xlsx"'
    return response


# ══════════════════════════════════════════════════════════════
# DETALLE + SOPORTES (comprobante por pago)
# ══════════════════════════════════════════════════════════════

@solo_financiera
def fin_pagos_detalle(request, pago_id):
    """Detalle de un pago realizado: datos del docente/colegio y gestión de soportes
    (subir/ver/descargar/eliminar). Espejo del detalle de viáticos en `PAGADA`."""
    pago = get_object_or_404(
        PagoRealizado.objects
        .select_related('profesor', 'colegio__colegio', 'marcado_por')
        .prefetch_related('soportes', 'soportes__subido_por'),
        pk=pago_id,
    )
    return render(request, 'financiera/pagos_detalle.html', {'pago': pago})


@solo_financiera
@require_POST
def fin_pagos_subir_soporte(request, pago_id):
    """Adjunta un comprobante a un pago realizado (mismo validador que viáticos)."""
    pago = get_object_or_404(PagoRealizado, pk=pago_id)
    archivo = request.FILES.get('archivo')
    if not archivo:
        messages.error(request, 'Selecciona un archivo para subir.')
        return redirect('fin_pagos_detalle', pago_id=pago.pk)

    error = validar_soporte(archivo)
    if error:
        messages.error(request, error)
        return redirect('fin_pagos_detalle', pago_id=pago.pk)

    SoportePagoProfesor.objects.create(
        pago=pago, archivo=archivo, nombre_original=archivo.name, subido_por=request.user)
    messages.success(request, 'Soporte de pago adjuntado.')
    return redirect('fin_pagos_detalle', pago_id=pago.pk)


@solo_financiera
@require_POST
def fin_pagos_eliminar_soporte(request, soporte_id):
    """Elimina un soporte (y su archivo en storage) subido por error."""
    soporte = get_object_or_404(SoportePagoProfesor.objects.select_related('pago'), pk=soporte_id)
    pago_id = soporte.pago_id
    soporte.archivo.delete(save=False)  # primero el storage, luego la fila
    soporte.delete()
    messages.success(request, 'Soporte eliminado.')
    return redirect('fin_pagos_detalle', pago_id=pago_id)


@solo_financiera
def fin_pago_soporte_descargar(request, soporte_id):
    """Ver (`?inline=1`) o descargar un soporte. Mismo proxy server-side que viáticos."""
    soporte = get_object_or_404(SoportePagoProfesor, pk=soporte_id)
    return _responder_soporte(soporte, inline=request.GET.get('inline') == '1')
