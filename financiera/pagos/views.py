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
from datetime import date, datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.areas import es_personal_financiera
from programacion.pagos.models import PagoRealizado, SoportePagoProfesor
from programacion.pagos.views import (
    construir_contexto_pagos, filas_pagos_por_tab,
    _generar_excel_pagos, _semana_label,
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
    """Marca/desmarca una fila `(profesor, colegio, fecha)` como pago realizado.

    `get_or_create` respeta el unique `(profesor, colegio, fecha)` (idempotente).
    `desmarcar` borra el `PagoRealizado`; antes elimina del storage los archivos de
    sus soportes para no dejarlos huérfanos (el CASCADE solo borra las filas)."""
    accion = request.POST.get('accion', 'marcar')
    try:
        profesor_id = int(request.POST.get('profesor_id', ''))
        colegio_id  = int(request.POST.get('colegio_id', ''))
        fecha_obj   = datetime.strptime(request.POST.get('fecha', ''), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'Datos inválidos'}, status=400)

    if accion == 'desmarcar':
        pagos = (PagoRealizado.objects
                 .filter(profesor_id=profesor_id, colegio_id=colegio_id, fecha=fecha_obj)
                 .prefetch_related('soportes'))
        for pago in pagos:
            for soporte in pago.soportes.all():
                soporte.archivo.delete(save=False)
        deleted, _ = pagos.delete()
        return JsonResponse({'ok': True, 'accion': 'desmarcado', 'deleted': deleted})

    # Tolerar coma decimal (locale es): el front debería mandar punto (|unlocalize),
    # pero normalizamos por si acaso para no rechazar el marcado.
    try:
        horas = float(request.POST.get('horas', '0').replace(',', '.'))
        valor = int(float(request.POST.get('valor', '0').replace(',', '.')))
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'Valor/horas inválidos'}, status=400)

    pago, created = PagoRealizado.objects.get_or_create(
        profesor_id=profesor_id, colegio_id=colegio_id, fecha=fecha_obj,
        defaults={'horas': horas, 'valor': valor, 'marcado_por': request.user},
    )
    return JsonResponse({'ok': True, 'accion': 'marcado', 'created': created, 'id': pago.id})


@solo_financiera
@require_POST
def fin_pagos_exportar(request):
    """Descarga el `.xlsx` del tab activo (reusa el generador de programación)."""
    try:
        fi = datetime.strptime(request.POST.get('fecha_inicio', ''), '%Y-%m-%d').date()
        ff = datetime.strptime(request.POST.get('fecha_fin', ''), '%Y-%m-%d').date()
    except ValueError:
        hoy = date.today()
        fi = hoy - timedelta(days=hoy.weekday())
        ff = fi + timedelta(days=4)

    tab = request.POST.get('tab', 'pendiente')
    filas = filas_pagos_por_tab(fi, ff, tab, modo='financiera')
    excel_bytes = _generar_excel_pagos(filas, _semana_label(fi, ff))

    sufijo = 'Realizados' if tab == 'realizado' else 'Pendientes'
    label = f"{fi.strftime('%Y%m%d')}_{ff.strftime('%Y%m%d')}"
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
