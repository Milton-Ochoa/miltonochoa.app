"""
Materialización de los pagos de monitores — **revisión en programación**, espejo de
``programacion.pagos`` pero con **fuente = simulacros** (no clases).

Cada ``AsignacionMonitor`` de un simulacro con ``fecha <= hoy`` genera una fila
``PagoMonitor`` de ``simulacro.valor``, agrupada por **semana** (lunes ancla). El ciclo
es ``BORRADOR → ENVIADO`` por lote semanal (``LoteMonitores``) y ``PAGADO`` por fila
(``PagoMonitor.fecha_pago``). **Sin gate por informe** (monitores no tienen informe).

Helpers PROPIOS a propósito: los de profesores están acoplados a ``Clase`` y a su
gate-por-informe; generalizarlos rompería ese flujo. Las fases de UI (6/7) construyen el
contexto con el mismo *shape* que ``construir_contexto_pagos`` para reusar los partials y
``_generar_excel_pagos``, pero la materialización vive aquí.
"""
from datetime import date, timedelta

from programacion.monitores.models import (
    AsignacionMonitor, LoteMonitores, PagoMonitor,
)


def _build_filas_monitores(fecha_inicio, fecha_fin):
    """Filas de pago calculadas desde las asignaciones de simulacros del rango.

    Una fila por ``(monitor, simulacro)`` — la asignación es la unidad de pago. El
    ``valor`` sale del simulacro (por monitor). Devuelve dicts con la clave de
    materialización ``(monitor_id, simulacro_id)`` implícita en los campos.
    """
    asignaciones = (
        AsignacionMonitor.objects
        .filter(simulacro__fecha__gte=fecha_inicio, simulacro__fecha__lte=fecha_fin)
        .select_related('simulacro', 'monitor')
        .order_by('simulacro__fecha', 'monitor__nombre')
    )
    filas = []
    for a in asignaciones:
        filas.append({
            'monitor_id':   a.monitor_id,
            'simulacro_id': a.simulacro_id,
            'fecha':        a.simulacro.fecha,
            'valor':        a.simulacro.valor or 0,
        })
    return filas


def preparar_lote_semana_monitores(inicio, fin, user=None):
    """Materializa (idempotente) el borrador de la semana canónica (lunes–domingo).

    NOTA: a diferencia de profesores (lunes–viernes, las clases son entre semana), la
    semana de monitores abarca **todo el fin de semana** — los simulacros suelen hacerse
    sábado/domingo y deben caer en su lote.

    Obtiene/crea el lote **BORRADOR** de la semana (convive con N lotes ENVIADO de la
    misma semana: constraint parcial) y sincroniza sus filas con las asignaciones:
    - crea filas para asignaciones nuevas;
    - refresca ``valor`` SOLO de filas no excluidas y no pagadas (si cambió el valor
      del simulacro); las de lotes **ENVIADO** quedan congeladas;
    - elimina filas **autogeneradas** (no excluidas, no pagadas, sin extras) cuya
      asignación ya no existe (se quitó el monitor del simulacro).

    Nunca resucita excluidas. Adopta filas existentes con la misma pareja
    ``(monitor, simulacro)`` (históricas ``lote=NULL`` y desacopladas al enviar),
    respetando el unique ``(monitor, simulacro)``.
    """
    lote, _ = LoteMonitores.objects.get_or_create(
        fecha_inicio=inicio, fecha_fin=fin, estado=LoteMonitores.Estado.BORRADOR)

    calc = {(f['monitor_id'], f['simulacro_id']): f
            for f in _build_filas_monitores(inicio, fin)}
    existentes = {
        (p.monitor_id, p.simulacro_id): p
        for p in PagoMonitor.objects
            .filter(fecha__gte=inicio, fecha__lte=fin)
            .select_related('lote')
            .prefetch_related('extras')
    }

    def _congelada(p):
        return (p.lote_id and p.lote_id != lote.id
                and p.lote.estado == LoteMonitores.Estado.ENVIADO)

    for key, f in calc.items():
        p = existentes.get(key)
        if p is None:
            PagoMonitor.objects.create(
                lote=lote,
                monitor_id=f['monitor_id'], simulacro_id=f['simulacro_id'],
                fecha=f['fecha'], valor=f['valor'],
            )
            continue
        if _congelada(p):
            continue
        cambios = []
        if p.lote_id != lote.id:
            p.lote = lote
            cambios.append('lote')
        if (not p.excluida and p.fecha_pago is None and p.valor != f['valor']):
            p.valor = f['valor']
            cambios.append('valor')
        if cambios:
            p.save(update_fields=cambios)

    # Limpiar filas autogeneradas de ESTE lote cuya asignación ya no existe.
    for key, p in existentes.items():
        if key in calc or p.lote_id != lote.id:
            continue
        if not p.excluida and p.fecha_pago is None and not p.extras.all():
            p.delete()

    return lote


def enviar_lote_monitores(lote, user):
    """BORRADOR → ENVIADO. A partir de aquí financiera lo ve y programación no edita.
    El envío es **definitivo por lote** (no hay reabrir).

    Antes de marcar, **desacopla** (``lote=None``) las filas **excluidas** para que el
    lote ENVIADO contenga exactamente lo enviado; un "Preparar pendientes" posterior las
    re-adopta a un BORRADOR nuevo. **Sin gate por informe** (monitores no tienen). Devuelve
    True si quedó ENVIADO; False si no tenía ninguna fila enviable (sigue BORRADOR).
    """
    from django.utils import timezone

    excluidas = [p.pk for p in lote.filas.all() if p.excluida]
    if excluidas:
        PagoMonitor.objects.filter(pk__in=excluidas).update(lote=None)
    if not lote.filas.exists():
        return False
    lote.estado = LoteMonitores.Estado.ENVIADO
    lote.enviado_en = timezone.now()
    lote.enviado_por = user
    lote.save(update_fields=['estado', 'enviado_en', 'enviado_por', 'actualizado_en'])
    return True


def preparar_pendientes_monitores(user=None):
    """Materializa el **backlog completo**: prepara (idempotente) el BORRADOR de todas
    las semanas con simulacros hasta hoy. Las filas ya enviadas quedan congeladas en sus
    lotes ENVIADO; las desacopladas al enviar se re-adoptan. Devuelve nº de semanas."""
    hoy = date.today()
    fechas = (AsignacionMonitor.objects
              .filter(simulacro__fecha__lte=hoy)
              .values_list('simulacro__fecha', flat=True).distinct())
    lunes_set = {f - timedelta(days=f.weekday()) for f in fechas}
    for lunes in lunes_set:
        # Semana completa (lunes–domingo): los simulacros de fin de semana cuentan.
        preparar_lote_semana_monitores(lunes, lunes + timedelta(days=6), user)
    # Borradores que quedaron vacíos no aportan nada al backlog: fuera.
    LoteMonitores.objects.filter(
        estado=LoteMonitores.Estado.BORRADOR, filas__isnull=True).delete()
    return len(lunes_set)
