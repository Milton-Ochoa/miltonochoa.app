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

from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from core.areas import es_personal_financiera
from programacion.exportar.models import PagoRealizado
from programacion.exportar.views import (
    construir_contexto_pagos, filas_pagos_por_tab,
    _generar_excel_pagos, _semana_label,
)

solo_financiera = user_passes_test(es_personal_financiera, login_url='login')


@solo_financiera
def fin_pagos_lista(request):
    """Tabla semanal de pagos (tabs pendiente/realizado). Mismo cálculo que
    programación (reutiliza `construir_contexto_pagos`), dibujado en el chrome
    financiera con las acciones de marcar/soporte."""
    return render(request, 'financiera/pagos.html', construir_contexto_pagos(request.GET))


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

    try:
        horas = float(request.POST.get('horas', 0))
        valor = int(request.POST.get('valor', 0))
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
    filas = filas_pagos_por_tab(fi, ff, tab)
    excel_bytes = _generar_excel_pagos(filas, _semana_label(fi, ff))

    sufijo = 'Realizados' if tab == 'realizado' else 'Pendientes'
    label = f"{fi.strftime('%Y%m%d')}_{ff.strftime('%Y%m%d')}"
    response = HttpResponse(
        excel_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="Pagos_{sufijo}_{label}.xlsx"'
    return response
