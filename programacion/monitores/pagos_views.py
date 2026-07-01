"""
Pagos de monitores — **revisión en programación** antes de financiera.

Espejo de ``programacion.pagos.views`` pero con **fuente = simulacros** (la
materialización vive en ``pagos_servicios.py``). Programación **prepara** el backlog
(materializa las filas ``PagoMonitor`` en lotes ``LoteMonitores`` BORRADOR), las
**revisa** (excluye filas, agrega costos extra) y las **envía** a financiera
(BORRADOR→ENVIADO). **Sin gate por informe** (monitores no tienen informe), así que
**no hay pestaña "Sin informe"**: solo *Por enviar* / *Enviados*.

``construir_contexto_monitores`` devuelve el **mismo shape** que
``construir_contexto_pagos`` para reusar los partials de ``pagos/`` y el generador de
Excel. Acepta ``modo='financiera'`` para que la Fase 7 (``financiera.monitores``) lo
importe igual que ``financiera.pagos`` importa ``construir_contexto_pagos``. Los
helpers genéricos sobre dicts (``_tipo_cuenta_display``, ``_generar_excel_pagos``,
``_label_rango``, ``_parse_fecha``, ``_rango_de``, ``_suma_valor``) se reutilizan de
``programacion.pagos.views`` — son agnósticos del modelo.
"""
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.areas import es_personal_programacion
from programacion.pagos.views import (
    _generar_excel_pagos, _label_rango, _parse_fecha, _rango_de, _suma_valor,
    _tipo_cuenta_display,
)

from programacion.viaticos.views import _responder_soporte

from .models import ExtraPagoMonitor, LoteMonitores, PagoMonitor, SoportePagoMonitor
from .pagos_servicios import (
    enviar_lote_monitores, preparar_pendientes_monitores,
)

solo_personal = user_passes_test(es_personal_programacion, login_url='login')


# ── Construcción del contexto (mismo shape que construir_contexto_pagos) ─────

def _fila_desde_pago_monitor(p):
    """Dict de fila (misma forma que las de profesores) desde una ``PagoMonitor``
    persistida, con su desglose y estado de pago. ``valor_total`` = base + extras.

    Las claves ``horas``/``valor_hora`` existen para que los partials/Excel compartidos
    no rompan, pero monitores no manejan horas: van vacías/cero (el detalle muestra el
    colegio en su lugar)."""
    monitor = p.monitor
    banco       = monitor.banco or ''
    tipo_cuenta = _tipo_cuenta_display(banco, monitor.tipo_cuenta or '')

    extras = [{'id': e.id, 'concepto': e.concepto, 'valor': e.valor} for e in p.extras.all()]
    total_extras = sum(e['valor'] for e in extras)
    valor_base = p.valor_base

    return {
        'fecha':        p.fecha,
        'monitor_id':   p.monitor_id,
        'simulacro_id': p.simulacro_id,
        'docente':      monitor.nombre_corto,
        'documento':    monitor.documento or '',
        'num_cuenta':   monitor.cuenta_bancaria or '',
        'tipo_cuenta':  tipo_cuenta,
        'banco':        banco,
        'colegio':      p.simulacro.nombre_colegio or '',
        'codigo':       (p.simulacro.colegio.codigo or '') if p.simulacro.colegio_id else '',
        'horas':        '',     # monitores no manejan horas
        'valor_hora':   0,
        'valor_base':   valor_base,
        'editado':      False,  # monitores no editan el valor base
        'extras':       extras,
        'total_extras': total_extras,
        'valor_total':  valor_base + total_extras,
        'excluida':     p.excluida,
        'pago_id':      p.id,
        'fecha_pago':   p.fecha_pago,
        'marcado_por':  ((p.marcado_por.get_full_name() or p.marcado_por.username)
                         if p.marcado_por else '—'),
        'n_soportes':   getattr(p, 'n_soportes', p.soportes.count()),
    }


def _filas_rango_monitores(estado, desde, hasta):
    """Filas persistidas (``PagoMonitor``) cuyo lote está en ``estado``, opcionalmente
    acotadas por fecha. Mantiene el desglose vía ``_fila_desde_pago_monitor``."""
    qs = (PagoMonitor.objects
          .filter(lote__estado=estado)
          .select_related('monitor', 'simulacro__colegio', 'marcado_por')
          .prefetch_related('extras')
          .annotate(n_soportes=Count('soportes'))
          .order_by('fecha', 'monitor__nombre'))
    if desde:
        qs = qs.filter(fecha__gte=desde)
    if hasta:
        qs = qs.filter(fecha__lte=hasta)
    return [_fila_desde_pago_monitor(p) for p in qs]


def _detalles_pagos_monitores(filas):
    """Mapa ``pago_id → {docente, colegio, valor_base, total, extras, editable}`` para
    el modal de detalle/gestión (se serializa con ``json_script``). Sin horas: el
    detalle de un monitor muestra el colegio del simulacro."""
    return {
        f['pago_id']: {
            'docente':    f['docente'],
            'colegio':    f['colegio'],
            'valor_base': f['valor_base'],
            'total':      f['valor_total'],
            'extras':     f['extras'],
            'editable':   f['fecha_pago'] is None and not f['excluida'],
        }
        for f in filas if f['pago_id']
    }


def construir_contexto_monitores(get, *, modo='programacion'):
    """Arma el contexto de la página de pagos de monitores como **backlog** (todas las
    semanas), con el mismo *shape* que ``construir_contexto_pagos``.

    Sin filtro de fechas → muestra todo; con filtro (``semana``/``hasta``) acota.
    - ``programacion``: *pendiente* = filas por **enviar** (lote BORRADOR, incluye las
      excluidas para re-incluirlas); *realizado* = filas ya **enviadas** (lote ENVIADO).
      **Sin** pestaña "sin informe" (monitores no tienen informe).
    - ``financiera``: **solo** lotes ENVIADO (sin excluidas), partidas por ``fecha_pago``."""
    desde, hasta = _rango_de(get)
    tab = get.get('tab', 'pendiente')

    if modo == 'financiera':
        enviadas = [f for f in _filas_rango_monitores(LoteMonitores.Estado.ENVIADO, desde, hasta)
                    if not f['excluida']]
        filas_pendientes = [f for f in enviadas if f['fecha_pago'] is None]
        filas_realizadas = [f for f in enviadas if f['fecha_pago'] is not None]
    else:
        filas_pendientes = _filas_rango_monitores(LoteMonitores.Estado.BORRADOR, desde, hasta)
        filas_realizadas = _filas_rango_monitores(LoteMonitores.Estado.ENVIADO, desde, hasta)

    filas_tab = filas_realizadas if tab == 'realizado' else filas_pendientes

    ctx = {
        'fecha_inicio':     desde.isoformat() if desde else '',
        'fecha_fin':        hasta.isoformat() if hasta else '',
        'fecha_max':        date.today().isoformat(),
        'semana_label':     _label_rango(desde, hasta),
        'filtro_aplicado':  bool(desde or hasta),
        'tab':              tab,
        'filas_pendientes': filas_pendientes,
        'filas_realizadas': filas_realizadas,
        'filas':            filas_tab,
        'total_valor':      _suma_valor(filas_tab),
        'total_pendiente':  _suma_valor(filas_pendientes),
        'total_realizado':  _suma_valor(filas_realizadas),
        'detalles_pagos':   _detalles_pagos_monitores(filas_pendientes + filas_realizadas),
    }
    if modo == 'programacion':
        por_enviar = [f for f in filas_pendientes if not f['excluida']]
        ctx.update({
            'tab_label_pendiente': 'Por enviar',
            'tab_label_realizado': 'Enviados',
            # No definimos `tab_label_sin_informe` → los partials no dibujan esa pestaña.
            'puede_enviar':        len(por_enviar) > 0,
            'total_por_enviar':    len(por_enviar),
        })
    return ctx


def filas_monitores_por_tab(fecha_inicio, fecha_fin, tab, *, modo='programacion'):
    """Filas para el Excel del tab, como backlog acotado al rango (vacío = todo).
    Excluye siempre las filas excluidas. Mismo ``modo`` que ``construir_contexto_monitores``."""
    get = {'tab': tab}
    if fecha_inicio:
        get['semana'] = fecha_inicio.isoformat() if hasattr(fecha_inicio, 'isoformat') else fecha_inicio
    if fecha_fin:
        get['hasta'] = fecha_fin.isoformat() if hasattr(fecha_fin, 'isoformat') else fecha_fin
    ctx = construir_contexto_monitores(get, modo=modo)
    return [f for f in ctx['filas'] if not f['excluida']]


# ── Página + Excel ──────────────────────────────────────────────────────────

@solo_personal
def monitores_pagos_lista(request):
    """GET: página de pagos de monitores (backlog, tabs por enviar/enviados).
    POST: descarga Excel del tab activo (rango opcional; vacío = todo el backlog).

    En GET materializa el backlog (idempotente) para que "Por enviar" muestre siempre
    todo lo pendiente sin depender de un botón manual."""
    if request.method == 'GET':
        preparar_pendientes_monitores(request.user)
        return render(request, 'monitores/pagos_monitores.html',
                      construir_contexto_monitores(request.GET, modo='programacion'))

    fi = _parse_fecha(request.POST.get('fecha_inicio', ''))
    ff = _parse_fecha(request.POST.get('fecha_fin', ''))
    tab = request.POST.get('tab', 'pendiente')

    filas = filas_monitores_por_tab(fi, ff, tab, modo='programacion')
    excel_bytes = _generar_excel_pagos(filas, _label_rango(fi, ff))

    sufijo = 'Enviados' if tab == 'realizado' else 'PorEnviar'
    rango = f"{fi.strftime('%Y%m%d')}_{ff.strftime('%Y%m%d')}" if fi and ff else 'todos'
    response = HttpResponse(
        excel_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="PagosMonitores_{sufijo}_{rango}.xlsx"'
    return response


# ══════════════════════════════════════════════════════════════
# REVISIÓN (programación): preparar pendientes · excluir · extras · enviar
# ══════════════════════════════════════════════════════════════
# Todas POST + redirect a la lista. Excluir/extras exigen que la fila esté en BORRADOR.
# El envío es definitivo (no hay reabrir).

def _volver_a_lista(request):
    """Redirige a la lista conservando el filtro de fechas (si lo hay) y la pestaña."""
    tab = request.POST.get('tab', 'pendiente')
    semana = request.POST.get('semana', '')
    hasta = request.POST.get('hasta', '')
    q = f'?tab={tab}'
    if semana:
        q += f'&semana={semana}'
    if hasta:
        q += f'&hasta={hasta}'
    return redirect(reverse('monitores_pagos_lista') + q)


def _pago_editable(pago):
    """True si la fila pertenece a un lote en BORRADOR (editable por programación)."""
    return bool(pago.lote_id and pago.lote.estado == LoteMonitores.Estado.BORRADOR)


@solo_personal
@require_POST
def monitores_pagos_preparar(request):
    """Prepara el backlog: materializa todas las semanas con simulacros hasta hoy no enviados."""
    n = preparar_pendientes_monitores(request.user)
    messages.success(request, f'Pendientes preparados ({n} semana(s)).')
    return _volver_a_lista(request)


@solo_personal
@require_POST
def monitores_pagos_enviar(request):
    """Envía a financiera **todo lo visible** (lotes BORRADOR con filas no excluidas dentro
    del rango filtrado, o todo si no hay filtro). El envío es definitivo."""
    desde, hasta = _rango_de(request.POST)
    qs = PagoMonitor.objects.filter(
        lote__estado=LoteMonitores.Estado.BORRADOR, excluida=False)
    if desde:
        qs = qs.filter(fecha__gte=desde)
    if hasta:
        qs = qs.filter(fecha__lte=hasta)
    lote_ids = set(qs.values_list('lote_id', flat=True))
    lotes = LoteMonitores.objects.filter(id__in=lote_ids, estado=LoteMonitores.Estado.BORRADOR)
    # `enviar_lote_monitores` desacopla las excluidas y devuelve False si el lote quedó
    # sin nada que enviar (sigue BORRADOR).
    n = sum(1 for lote in lotes if enviar_lote_monitores(lote, request.user))
    if n:
        messages.success(request, f'Enviado a financiera ({n} semana(s)).')
    else:
        messages.error(request, 'No hay pagos enviables. Las filas excluidas no se envían.')
    return _volver_a_lista(request)


@solo_personal
@require_POST
def monitores_pagos_excluir_fila(request, pago_id):
    """Excluye o vuelve a incluir una fila del envío a financiera (toggle)."""
    pago = get_object_or_404(PagoMonitor.objects.select_related('lote'), pk=pago_id)
    if not _pago_editable(pago):
        messages.error(request, 'Esta fila ya no es editable.')
    else:
        pago.excluida = not pago.excluida
        pago.save(update_fields=['excluida'])
        messages.success(request, 'Fila excluida del envío.' if pago.excluida else 'Fila incluida.')
    return _volver_a_lista(request)


@solo_personal
@require_POST
def monitores_pagos_agregar_extra(request, pago_id):
    """Agrega un costo extra (concepto + valor) al desglose de una fila."""
    pago = get_object_or_404(PagoMonitor.objects.select_related('lote'), pk=pago_id)
    if not _pago_editable(pago):
        messages.error(request, 'Esta fila ya no es editable.')
        return _volver_a_lista(request)
    concepto = (request.POST.get('concepto', '') or '').strip()
    raw = (request.POST.get('valor', '') or '').strip().replace('.', '').replace(',', '')
    try:
        valor = int(raw)
    except (ValueError, TypeError):
        valor = 0
    if not concepto or valor <= 0:
        messages.error(request, 'Indica un concepto y un valor mayor que cero.')
        return _volver_a_lista(request)
    ExtraPagoMonitor.objects.create(
        pago=pago, concepto=concepto, valor=valor, orden=pago.extras.count())
    messages.success(request, 'Costo extra agregado.')
    return _volver_a_lista(request)


@solo_personal
@require_POST
def monitores_pagos_eliminar_extra(request, extra_id):
    """Elimina un costo extra del desglose."""
    extra = get_object_or_404(
        ExtraPagoMonitor.objects.select_related('pago__lote'), pk=extra_id)
    if not _pago_editable(extra.pago):
        messages.error(request, 'Esta fila ya no es editable.')
    else:
        extra.delete()
        messages.success(request, 'Costo extra eliminado.')
    return _volver_a_lista(request)


# ══════════════════════════════════════════════════════════════
# DETALLE DE PAGO — SOLO LECTURA (el comprobante lo gestiona financiera)
# ══════════════════════════════════════════════════════════════

@solo_personal
def monitores_pago_detalle(request, pago_id):
    """Detalle de solo lectura de un pago de monitor: datos del monitor/simulacro y
    los soportes adjuntos (ver/descargar, sin subir ni eliminar — eso es de financiera)."""
    pago = get_object_or_404(
        PagoMonitor.objects
        .select_related('monitor', 'simulacro__colegio', 'marcado_por', 'lote')
        .prefetch_related('extras', 'soportes', 'soportes__subido_por'),
        pk=pago_id,
    )
    return render(request, 'monitores/pago_monitor_detalle.html', {'pago': pago})


@solo_personal
def monitores_pago_soporte_descargar(request, soporte_id):
    """Ver (``?inline=1``) o descargar un soporte de pago de monitor desde programación
    (solo lectura). Mismo proxy server-side que financiera; difiere en el gate."""
    soporte = get_object_or_404(SoportePagoMonitor, pk=soporte_id)
    return _responder_soporte(soporte, inline=request.GET.get('inline') == '1')
