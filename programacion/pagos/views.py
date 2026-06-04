"""
Pagos semanales a profesores — **revisión en programación** antes de financiera.

Calcula la liquidación semanal por fila `(profesor, colegio, día)` a partir de las
clases dictadas. Programación **prepara** el borrador de la semana (materializa las
filas en un `LotePagos` BORRADOR), las **revisa** (edita el valor base, excluye filas,
agrega costos extra del desglose) y las **envía** a financiera (BORRADOR→ENVIADO).
**Financiera solo ve las filas de lotes ENVIADO**, ve el desglose, marca el pago y
sube/elimina soportes (financiera/pagos).

Los helpers de cálculo (`construir_contexto_pagos`, `filas_pagos_por_tab`,
`_generar_excel_pagos`, `_semana_label`) son **compartidos**: financiera los importa con
`modo='financiera'` para reusar exactamente el mismo cálculo (BD única, sin duplicar).
`_build_filas_pagos` (cálculo puro desde clases) alimenta la materialización;
`_filas_desde_lote` lee las filas ya persistidas (con su desglose).
"""
import io
from datetime import date, datetime, timedelta

from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.db.models import Count
from django.utils import timezone
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.views.decorators.http import require_POST
from core.areas import es_personal_programacion
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from programacion.colegios.models import Clase
from programacion.pagos.models import ExtraPago, LotePagos, PagoRealizado, SoportePagoProfesor
from programacion.viaticos.views import _responder_soporte


MESES_ES_LARGO = ['', 'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
                  'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']


def _semana_label(fecha_inicio, fecha_fin):
    if fecha_inicio.month == fecha_fin.month:
        return (f"Semana del {fecha_inicio.day} al {fecha_fin.day} "
                f"de {MESES_ES_LARGO[fecha_inicio.month]} de {fecha_inicio.year}")
    return (f"Semana del {fecha_inicio.day} de {MESES_ES_LARGO[fecha_inicio.month]} "
            f"al {fecha_fin.day} de {MESES_ES_LARGO[fecha_fin.month]} de {fecha_fin.year}")


def _build_filas_pagos(fecha_inicio, fecha_fin):
    """
    Devuelve lista de dicts con los datos de pago agrupados por
    (fecha, profesor, colegio), sumando horas del día.
    """
    clases = list(
        Clase.objects
        .filter(
            fecha__gte=fecha_inicio, fecha__lte=fecha_fin,
            cancelada=False, es_evento=False,
        )
        .select_related(
            'profesor',
            'bloque__colegio__colegio',
        )
        .values(
            'fecha',
            'profesor_id',
            'profesor__nombre',
            'profesor__apellido',
            'profesor__documento',
            'profesor__cuenta_bancaria',
            'profesor__tipo_cuenta',
            'profesor__banco',
            'bloque__colegio_id',
            'bloque__colegio__colegio__nombre',
            'bloque__colegio__colegio__codigo',
            'bloque__colegio__valor_hora',
            'bloque__hora_inicio',
            'bloque__hora_fin',
        )
    )

    # Agrupar: (fecha, profesor_id, colegio_id) → minutos + info
    grupos = {}
    for c in clases:
        if not c['profesor_id']:
            continue
        key = (c['fecha'], c['profesor_id'], c['bloque__colegio_id'])
        hi = c['bloque__hora_inicio']
        hf = c['bloque__hora_fin']
        minutos = 0
        if hi and hf:
            minutos = max(0, (hf.hour * 60 + hf.minute) - (hi.hour * 60 + hi.minute))
        if key not in grupos:
            grupos[key] = {'minutos': 0, 'info': c}
        grupos[key]['minutos'] += minutos

    filas = []
    for (fecha, prof_id, col_id), data in sorted(grupos.items(), key=lambda x: (x[0][0], x[0][1])):
        info = data['info']
        horas = data['minutos'] / 60
        valor_hora = info['bloque__colegio__valor_hora'] or 0
        valor_total = round(horas * valor_hora)

        nombre   = info['profesor__nombre'] or ''
        apellido = info['profesor__apellido'] or ''
        pn = nombre.split()[0] if nombre else ''
        pa = apellido.split()[0] if apellido else ''
        nombre_corto = f"{pn} {pa}".strip()

        # Tipo de cuenta: "Ahorros a la mano" si Daviplata, else valor normal
        banco      = info['profesor__banco'] or ''
        tipo_raw   = info['profesor__tipo_cuenta'] or ''
        tipo_cuenta = 'Ahorros a la mano' if banco == 'Daviplata' else tipo_raw

        filas.append({
            'fecha':       fecha,
            'profesor_id': prof_id,
            'colegio_id':  col_id,
            'docente':     nombre_corto,
            'documento':   info['profesor__documento'] or '',
            'num_cuenta':  info['profesor__cuenta_bancaria'] or '',
            'tipo_cuenta': tipo_cuenta,
            'banco':       banco,
            'colegio':     info['bloque__colegio__colegio__nombre'] or '',
            'codigo':      info['bloque__colegio__colegio__codigo'] or '',
            'horas':       horas,
            'valor_hora':  valor_hora,
            'valor_total': valor_total,
        })

    return filas


def _semana_de(get):
    """Resuelve la semana **canónica** (lunes, viernes) desde `get` (`?semana=`).

    Siempre se ancla al **lunes** de la semana elegida (o de hoy si no hay `?semana=`);
    el viernes es lunes+4. El lote se llavea con este par canónico, así la navegación es
    semanal y la llave del lote es estable aunque el usuario teclee fechas raras."""
    base = date.today()
    semana_str = get.get('semana', '')
    if semana_str:
        try:
            base = datetime.strptime(semana_str, '%Y-%m-%d').date()
        except ValueError:
            base = date.today()
    lunes = base - timedelta(days=base.weekday())
    return lunes, lunes + timedelta(days=4)


def _fila_desde_pago(p):
    """Construye el dict de fila (misma forma que `_build_filas_pagos`) desde una
    `PagoRealizado` persistida, añadiendo el desglose y el estado de pago.

    `valor_total` = total (valor base —posiblemente editado— + extras), para que la
    tabla/Excel sigan mostrando el monto final en la columna VALOR."""
    nombre   = p.profesor.nombre or ''
    apellido = p.profesor.apellido or ''
    pn = nombre.split()[0] if nombre else ''
    pa = apellido.split()[0] if apellido else ''
    nombre_corto = f"{pn} {pa}".strip()

    banco      = p.profesor.banco or ''
    tipo_raw   = p.profesor.tipo_cuenta or ''
    tipo_cuenta = 'Ahorros a la mano' if banco == 'Daviplata' else tipo_raw

    extras = [{'id': e.id, 'concepto': e.concepto, 'valor': e.valor} for e in p.extras.all()]
    total_extras = sum(e['valor'] for e in extras)
    valor_base = p.valor_base

    return {
        'fecha':        p.fecha,
        'profesor_id':  p.profesor_id,
        'colegio_id':   p.colegio_id,
        'docente':      nombre_corto,
        'documento':    p.profesor.documento or '',
        'num_cuenta':   p.profesor.cuenta_bancaria or '',
        'tipo_cuenta':  tipo_cuenta,
        'banco':        banco,
        'colegio':      p.colegio.colegio.nombre or '',
        'codigo':       p.colegio.colegio.codigo or '',
        'horas':        p.horas,
        'valor_hora':   p.colegio.valor_hora or 0,
        'valor_base':   valor_base,
        'editado':      p.valor_base_editado is not None,
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


def _filas_desde_lote(lote):
    """Filas persistidas de un lote (incluye las **excluidas**, marcadas con `excluida`,
    para que programación pueda re-incluirlas). El llamador filtra excluidas si toca."""
    pagos = (
        PagoRealizado.objects
        .filter(lote=lote)
        .select_related('profesor', 'colegio__colegio', 'marcado_por')
        .prefetch_related('extras')
        .annotate(n_soportes=Count('soportes'))
        .order_by('fecha', 'profesor__nombre')
    )
    return [_fila_desde_pago(p) for p in pagos]


def preparar_lote_semana(inicio, fin, user=None):
    """Materializa (idempotente) el borrador de la semana canónica (lunes–viernes).

    Crea el `LotePagos` si no existe. Si está ENVIADO, no toca nada (bloqueado). Si está
    BORRADOR, sincroniza las filas con el cálculo desde clases:
    - crea filas para clases nuevas;
    - refresca `horas`/`valor` SOLO de filas sin override, no excluidas y no pagadas;
    - elimina filas **autogeneradas** (sin override, sin extras, no excluidas, no pagadas)
      cuya clase ya no existe (cancelada).

    Nunca resucita excluidas ni pisa valores editados. Adopta al lote filas existentes con
    la misma tripleta (p. ej. históricas `lote=NULL`), respetando el unique
    `(profesor, colegio, fecha)`."""
    lote, _ = LotePagos.objects.get_or_create(fecha_inicio=inicio, fecha_fin=fin)
    if lote.estado == LotePagos.Estado.ENVIADO:
        return lote

    calc = {(f['profesor_id'], f['colegio_id'], f['fecha']): f
            for f in _build_filas_pagos(inicio, fin)}
    existentes = {
        (p.profesor_id, p.colegio_id, p.fecha): p
        for p in PagoRealizado.objects
            .filter(fecha__gte=inicio, fecha__lte=fin)
            .prefetch_related('extras')
    }

    for key, f in calc.items():
        p = existentes.get(key)
        if p is None:
            PagoRealizado.objects.create(
                lote=lote,
                profesor_id=f['profesor_id'], colegio_id=f['colegio_id'], fecha=f['fecha'],
                horas=f['horas'], valor=f['valor_total'],
            )
            continue
        cambios = []
        if p.lote_id != lote.id:
            p.lote = lote
            cambios.append('lote')
        if (p.valor_base_editado is None and not p.excluida and p.fecha_pago is None
                and (p.horas != f['horas'] or p.valor != f['valor_total'])):
            p.horas = f['horas']
            p.valor = f['valor_total']
            cambios += ['horas', 'valor']
        if cambios:
            p.save(update_fields=cambios)

    # Limpiar filas autogeneradas de ESTE lote que ya no salen en el cálculo.
    for key, p in existentes.items():
        if key in calc or p.lote_id != lote.id:
            continue
        if (p.valor_base_editado is None and not p.excluida and p.fecha_pago is None
                and not p.extras.all()):
            p.delete()

    return lote


def enviar_lote(lote, user):
    """BORRADOR → ENVIADO. A partir de aquí financiera lo ve y programación no edita."""
    lote.estado = LotePagos.Estado.ENVIADO
    lote.enviado_en = timezone.now()
    lote.enviado_por = user
    lote.save(update_fields=['estado', 'enviado_en', 'enviado_por', 'actualizado_en'])


def desenviar_lote(lote):
    """ENVIADO → BORRADOR, **solo si ninguna fila está pagada**. Devuelve True si lo hizo."""
    if lote.filas.filter(fecha_pago__isnull=False).exists():
        return False
    lote.estado = LotePagos.Estado.BORRADOR
    lote.enviado_en = None
    lote.enviado_por = None
    lote.save(update_fields=['estado', 'enviado_en', 'enviado_por', 'actualizado_en'])
    return True


def _desglose_texto(f):
    """Texto del desglose de una fila para el Excel: ``Base: $X; Concepto: $Y``.
    Vacío si la fila no tiene costos extra (la columna VALOR ya muestra el total)."""
    extras = f.get('extras') or []
    if not extras:
        return ''
    partes = [f"Base: ${f.get('valor_base', f['valor_total']):,}"]
    partes += [f"{e['concepto']}: ${e['valor']:,}" for e in extras]
    return '; '.join(partes)


def _generar_excel_pagos(filas, semana_label):
    """Genera el Excel de pagos. Una fila por pago `(profesor, colegio, día)` con el monto
    final en VALOR; la columna DESGLOSE detalla base + costos extra cuando los hay."""
    wb = Workbook()
    ws = wb.active
    ws.title = 'Pagos'

    NUM_COLS = 10
    COLS = ['FECHA', 'DOCENTE', 'DOCUMENTO', 'N° DE CUENTA',
            'TIPO DE CUENTA', 'BANCO', 'COLEGIO', 'CODIGO', 'VALOR', 'DESGLOSE']

    HEADER_FILL  = 'FF1F3864'  # azul oscuro
    SUBHDR_FILL  = 'FFD6E4F0'  # azul claro
    TOTAL_FILL   = 'FFD6DCE4'

    thin = Side(style='thin', color='000000')
    borde = Border(left=thin, right=thin, top=thin, bottom=thin)

    def _celda(row, col, valor='', bold=False, fill=None, color='000000',
               h='center', v='center', fmt=None, borde_=True):
        cell = ws.cell(row, col, valor)
        cell.font = Font(name='Arial', size=10, bold=bold, color=color)
        cell.alignment = Alignment(horizontal=h, vertical=v, wrap_text=True)
        if fill:
            cell.fill = PatternFill('solid', fgColor=fill)
        if borde_:
            cell.border = borde
        if fmt:
            cell.number_format = fmt
        return cell

    # Fila 1: título semana
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=NUM_COLS)
    _celda(1, 1, semana_label, bold=True, fill='FFD9E1F2', color='FF1F3864',
           borde_=False)
    ws.row_dimensions[1].height = 20

    # Fila 2: cabeceras
    for ci, col_name in enumerate(COLS, start=1):
        _celda(2, ci, col_name, bold=True, fill='FFB8CCE4', color='FF1F3864')
    ws.row_dimensions[2].height = 22

    # Filas de datos
    MESES_ES_ABREV = ['', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
                      'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

    for i, f in enumerate(filas, start=3):
        fill_row = 'FFFFFFFF' if i % 2 == 1 else 'FFF2F6FC'
        fecha_str = f"{f['fecha'].day:02d}/{f['fecha'].month:02d}/{f['fecha'].year}"
        _celda(i, 1, fecha_str,       fill=fill_row, h='center')
        _celda(i, 2, f['docente'],    fill=fill_row, h='left')
        _celda(i, 3, f['documento'],  fill=fill_row, h='center')
        _celda(i, 4, f['num_cuenta'], fill=fill_row, h='center')
        _celda(i, 5, f['tipo_cuenta'],fill=fill_row, h='center')
        _celda(i, 6, f['banco'],      fill=fill_row, h='center')
        _celda(i, 7, f['colegio'],    fill=fill_row, h='left')
        _celda(i, 8, f['codigo'],     fill=fill_row, h='center')
        # Valor como número para que Excel pueda sumar
        cell_val = ws.cell(i, 9, f['valor_total'])
        cell_val.font = Font(name='Arial', size=10)
        cell_val.alignment = Alignment(horizontal='right', vertical='center')
        cell_val.fill = PatternFill('solid', fgColor=fill_row)
        cell_val.border = borde
        cell_val.number_format = '"$"#,##0'
        _celda(i, 10, _desglose_texto(f), fill=fill_row, h='left')
        ws.row_dimensions[i].height = 18

    # Fila TOTAL
    total_row = 3 + len(filas)
    ws.merge_cells(start_row=total_row, start_column=1,
                   end_row=total_row, end_column=8)
    _celda(total_row, 1, 'TOTAL', bold=True, fill=TOTAL_FILL, h='right')
    total_val = sum(f['valor_total'] for f in filas)
    cell_t = ws.cell(total_row, 9, total_val)
    cell_t.font = Font(name='Arial', size=10, bold=True)
    cell_t.alignment = Alignment(horizontal='right', vertical='center')
    cell_t.fill = PatternFill('solid', fgColor=TOTAL_FILL)
    cell_t.border = borde
    cell_t.number_format = '"$"#,##0'
    _celda(total_row, 10, '', fill=TOTAL_FILL)
    ws.row_dimensions[total_row].height = 22

    # Anchos de columna
    anchos = [12, 22, 14, 18, 18, 16, 30, 10, 14, 40]
    for ci, ancho in enumerate(anchos, start=1):
        ws.column_dimensions[get_column_letter(ci)].width = ancho

    ws.freeze_panes = 'A3'
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _enriquecer_preview(filas):
    """Da a las filas calculadas (sin lote) las mismas claves que `_fila_desde_pago`,
    para que plantilla/Excel funcionen igual antes de preparar la semana."""
    for f in filas:
        f.setdefault('valor_base', f['valor_total'])
        f.setdefault('extras', [])
        f.setdefault('total_extras', 0)
        f.setdefault('excluida', False)
        f.setdefault('pago_id', None)
        f.setdefault('fecha_pago', None)
        f.setdefault('marcado_por', '—')
        f.setdefault('n_soportes', 0)
    return filas


def _filas_semana(get, *, modo):
    """Filas de la semana según el modo, junto al lote y el rango canónico.

    - `programacion`: si hay lote → sus filas (incl. excluidas, marcadas); si no →
      preview calculado desde clases (estado "sin preparar").
    - `financiera`: **solo** las filas de un lote ENVIADO (sin excluidas); si no, vacío.

    Devuelve `(lunes, viernes, lote, filas)`."""
    lunes, viernes = _semana_de(get)
    lote = LotePagos.objects.filter(fecha_inicio=lunes, fecha_fin=viernes).first()

    if modo == 'financiera':
        filas = ([f for f in _filas_desde_lote(lote) if not f['excluida']]
                 if (lote and lote.enviado) else [])
    else:
        filas = (_filas_desde_lote(lote) if lote
                 else _enriquecer_preview(_build_filas_pagos(lunes, viernes)))
    return lunes, viernes, lote, filas


def _split_por_pago(filas):
    """Parte filas en (pendientes, realizadas) por `fecha_pago`; las excluidas, que nunca
    se pagan, caen en pendientes. Devuelve también los totales (sin contar excluidas)."""
    pendientes = [f for f in filas if f['fecha_pago'] is None]
    realizadas = [f for f in filas if f['fecha_pago'] is not None]
    return pendientes, realizadas


def _suma_valor(filas):
    return sum(f['valor_total'] for f in filas if not f['excluida'])


def construir_contexto_pagos(get, *, modo='programacion'):
    """Arma el contexto de la página semanal de pagos (tabs pendiente/realizado).

    Compartido por **programación** (revisión/edición) y **financiera** (marcar+soportes).
    `modo` decide la fuente: programación ve el borrador o el preview; financiera **solo**
    los lotes ENVIADO. Mantiene las claves históricas (`filas_pendientes`, `filas_realizadas`,
    `filas`, `total_*`, `semana_label`, …); en `programacion` añade el estado del lote y los
    flags de acción (`puede_preparar/editar/enviar/desenviar`, `hay_cambios_sin_preparar`)."""
    lunes, viernes, lote, filas = _filas_semana(get, modo=modo)
    tab = get.get('tab', 'pendiente')

    filas_pendientes, filas_realizadas = _split_por_pago(filas)
    filas_tab = filas_pendientes if tab == 'pendiente' else filas_realizadas

    ctx = {
        'fecha_inicio':     lunes.isoformat(),
        'fecha_fin':        viernes.isoformat(),
        'fecha_max':        date.today().isoformat(),
        'semana_label':     _semana_label(lunes, viernes),
        'tab':              tab,
        'filas_pendientes': filas_pendientes,
        'filas_realizadas': filas_realizadas,
        'filas':            filas_tab,
        'total_valor':      _suma_valor(filas_tab),
        'total_pendiente':  _suma_valor(filas_pendientes),
        'total_realizado':  _suma_valor(filas_realizadas),
    }

    if modo == 'programacion':
        estado_lote = lote.estado if lote else 'SIN_PREPARAR'
        filas_a_enviar = [f for f in filas if not f['excluida']]
        # ¿Aparecen clases nuevas que aún no están en el borrador? (solo en BORRADOR)
        hay_cambios = False
        if lote and lote.estado == LotePagos.Estado.BORRADOR:
            calc_keys = {(f['profesor_id'], f['colegio_id'], f['fecha'])
                         for f in _build_filas_pagos(lunes, viernes)}
            lote_keys = {(f['profesor_id'], f['colegio_id'], f['fecha']) for f in filas}
            hay_cambios = bool(calc_keys - lote_keys)
        ctx.update({
            'estado_lote':              estado_lote,
            'lote_id':                  lote.id if lote else None,
            'enviado_en':               lote.enviado_en if lote else None,
            'puede_preparar':           estado_lote in ('SIN_PREPARAR', 'BORRADOR'),
            'puede_editar':             estado_lote == 'BORRADOR',
            'puede_enviar':             estado_lote == 'BORRADOR' and len(filas_a_enviar) > 0,
            'puede_desenviar':          bool(lote and lote.enviado
                                             and not any(f['fecha_pago'] for f in filas)),
            'hay_cambios_sin_preparar': hay_cambios,
        })
    return ctx


def filas_pagos_por_tab(fecha_inicio, fecha_fin, tab, *, modo='programacion'):
    """Filas de la semana (de `fecha_inicio`) filtradas por tab, para el Excel. Excluye
    siempre las filas excluidas. Mismo `modo` que `construir_contexto_pagos`."""
    lunes = fecha_inicio - timedelta(days=fecha_inicio.weekday())
    lote = LotePagos.objects.filter(
        fecha_inicio=lunes, fecha_fin=lunes + timedelta(days=4)).first()

    if modo == 'financiera':
        todas = ([f for f in _filas_desde_lote(lote) if not f['excluida']]
                 if (lote and lote.enviado) else [])
    elif lote:
        todas = [f for f in _filas_desde_lote(lote) if not f['excluida']]
    else:
        todas = _enriquecer_preview(_build_filas_pagos(lunes, lunes + timedelta(days=4)))

    es_realizado = tab == 'realizado'
    return [f for f in todas if (f['fecha_pago'] is not None) == es_realizado]


@user_passes_test(es_personal_programacion, login_url='login')
def pagos_lista(request):
    """GET: página de pagos (tabs pendiente/realizado). POST: descarga Excel."""
    hoy = date.today()
    lunes   = hoy - timedelta(days=hoy.weekday())
    viernes = lunes + timedelta(days=4)

    if request.method == 'GET':
        return render(request, 'pagos/pagos.html',
                      construir_contexto_pagos(request.GET, modo='programacion'))

    # POST: descarga Excel del tab activo
    fi_str = request.POST.get('fecha_inicio', '')
    ff_str = request.POST.get('fecha_fin', '')
    tab    = request.POST.get('tab', 'pendiente')
    try:
        fi = datetime.strptime(fi_str, '%Y-%m-%d').date()
        ff = datetime.strptime(ff_str, '%Y-%m-%d').date()
    except ValueError:
        fi, ff = lunes, viernes

    filas = filas_pagos_por_tab(fi, ff, tab, modo='programacion')
    semana_label = _semana_label(fi, ff)
    excel_bytes  = _generar_excel_pagos(filas, semana_label)

    sufijo = 'Realizados' if tab == 'realizado' else 'Pendientes'
    label  = f"{fi.strftime('%Y%m%d')}_{ff.strftime('%Y%m%d')}"
    response = HttpResponse(
        excel_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = (
        f'attachment; filename="Pagos_{sufijo}_{label}.xlsx"'
    )
    return response


# ══════════════════════════════════════════════════════════════
# REVISIÓN (programación): preparar · editar valor · excluir · extras · enviar
# ══════════════════════════════════════════════════════════════
# Programación revisa el borrador de la semana y lo envía a financiera. Todas las
# acciones son POST + redirect a la lista (la página re-renderiza con datos frescos);
# editar/excluir/extras exigen que la semana esté en BORRADOR.

def _volver_a_lista(semana, tab='pendiente'):
    """Redirige a la lista conservando semana y pestaña activa."""
    return redirect(f"{reverse('pagos_lista')}?semana={semana}&tab={tab}")


def _pago_editable(pago):
    """True si la fila pertenece a un lote en BORRADOR (editable por programación)."""
    return bool(pago.lote_id and pago.lote.estado == LotePagos.Estado.BORRADOR)


@user_passes_test(es_personal_programacion, login_url='login')
@require_POST
def pagos_preparar_semana(request):
    """Materializa (o re-sincroniza) el borrador de la semana desde las clases."""
    semana = request.POST.get('semana', '')
    lunes, viernes = _semana_de({'semana': semana})
    preparar_lote_semana(lunes, viernes, request.user)
    messages.success(request, 'Borrador de la semana preparado para revisión.')
    return _volver_a_lista(lunes.isoformat(), request.POST.get('tab', 'pendiente'))


@user_passes_test(es_personal_programacion, login_url='login')
@require_POST
def pagos_enviar_semana(request):
    """Envía la semana a financiera (BORRADOR→ENVIADO). Bloquea edición posterior."""
    semana = request.POST.get('semana', '')
    lunes, viernes = _semana_de({'semana': semana})
    lote = LotePagos.objects.filter(fecha_inicio=lunes, fecha_fin=viernes).first()
    if not lote:
        messages.error(request, 'Primero prepara el borrador de la semana.')
    elif lote.estado != LotePagos.Estado.BORRADOR:
        messages.info(request, 'Esta semana ya fue enviada a financiera.')
    elif not lote.filas.filter(excluida=False).exists():
        messages.error(request, 'No hay filas para enviar (todas están excluidas o vacías).')
    else:
        enviar_lote(lote, request.user)
        messages.success(request, 'Semana enviada a financiera.')
    return _volver_a_lista(lunes.isoformat(), request.POST.get('tab', 'pendiente'))


@user_passes_test(es_personal_programacion, login_url='login')
@require_POST
def pagos_desenviar_semana(request):
    """Reabre la semana (ENVIADO→BORRADOR) solo si ninguna fila está pagada."""
    semana = request.POST.get('semana', '')
    lunes, viernes = _semana_de({'semana': semana})
    lote = LotePagos.objects.filter(fecha_inicio=lunes, fecha_fin=viernes).first()
    if not lote or not lote.enviado:
        messages.error(request, 'La semana no está enviada.')
    elif desenviar_lote(lote):
        messages.success(request, 'Semana reabierta para edición.')
    else:
        messages.error(request, 'No se puede reabrir: financiera ya pagó alguna fila.')
    return _volver_a_lista(lunes.isoformat(), request.POST.get('tab', 'pendiente'))


@user_passes_test(es_personal_programacion, login_url='login')
@require_POST
def pagos_editar_valor(request, pago_id):
    """Sobrescribe el valor base de una fila (o lo restaura al calculado si llega vacío)."""
    pago = get_object_or_404(PagoRealizado.objects.select_related('lote'), pk=pago_id)
    semana = request.POST.get('semana', pago.fecha.isoformat())
    if not _pago_editable(pago):
        messages.error(request, 'La semana no es editable.')
        return _volver_a_lista(semana, request.POST.get('tab', 'pendiente'))
    raw = (request.POST.get('valor', '') or '').strip().replace(',', '.')
    try:
        pago.valor_base_editado = None if raw == '' else int(float(raw))
    except (ValueError, TypeError):
        messages.error(request, 'Valor inválido.')
        return _volver_a_lista(semana, request.POST.get('tab', 'pendiente'))
    pago.save(update_fields=['valor_base_editado'])
    messages.success(request, 'Valor actualizado.')
    return _volver_a_lista(semana, request.POST.get('tab', 'pendiente'))


@user_passes_test(es_personal_programacion, login_url='login')
@require_POST
def pagos_excluir_fila(request, pago_id):
    """Excluye o vuelve a incluir una fila del envío a financiera (toggle)."""
    pago = get_object_or_404(PagoRealizado.objects.select_related('lote'), pk=pago_id)
    semana = request.POST.get('semana', pago.fecha.isoformat())
    if not _pago_editable(pago):
        messages.error(request, 'La semana no es editable.')
    else:
        pago.excluida = not pago.excluida
        pago.save(update_fields=['excluida'])
        messages.success(request, 'Fila excluida.' if pago.excluida else 'Fila incluida.')
    return _volver_a_lista(semana, request.POST.get('tab', 'pendiente'))


@user_passes_test(es_personal_programacion, login_url='login')
@require_POST
def pagos_agregar_extra(request, pago_id):
    """Agrega un costo extra (concepto + valor) al desglose de una fila."""
    pago = get_object_or_404(PagoRealizado.objects.select_related('lote'), pk=pago_id)
    semana = request.POST.get('semana', pago.fecha.isoformat())
    tab = request.POST.get('tab', 'pendiente')
    if not _pago_editable(pago):
        messages.error(request, 'La semana no es editable.')
        return _volver_a_lista(semana, tab)
    concepto = (request.POST.get('concepto', '') or '').strip()
    raw = (request.POST.get('valor', '') or '').strip().replace('.', '').replace(',', '')
    try:
        valor = int(raw)
    except (ValueError, TypeError):
        valor = 0
    if not concepto or valor <= 0:
        messages.error(request, 'Indica un concepto y un valor mayor que cero.')
        return _volver_a_lista(semana, tab)
    siguiente = (pago.extras.count())
    ExtraPago.objects.create(pago=pago, concepto=concepto, valor=valor, orden=siguiente)
    messages.success(request, 'Costo extra agregado.')
    return _volver_a_lista(semana, tab)


@user_passes_test(es_personal_programacion, login_url='login')
@require_POST
def pagos_eliminar_extra(request, extra_id):
    """Elimina un costo extra del desglose."""
    extra = get_object_or_404(ExtraPago.objects.select_related('pago__lote'), pk=extra_id)
    semana = request.POST.get('semana', extra.pago.fecha.isoformat())
    tab = request.POST.get('tab', 'pendiente')
    if not _pago_editable(extra.pago):
        messages.error(request, 'La semana no es editable.')
    else:
        extra.delete()
        messages.success(request, 'Costo extra eliminado.')
    return _volver_a_lista(semana, tab)


# ══════════════════════════════════════════════════════════════
# DETALLE DE PAGO — SOLO LECTURA (el comprobante lo gestiona financiera)
# ══════════════════════════════════════════════════════════════
# Marcar el pago y subir/eliminar soportes es responsabilidad de financiera
# (financiera/pagos). Programación solo calcula, ve el listado y consulta los
# comprobantes adjuntos en solo lectura.

@user_passes_test(es_personal_programacion, login_url='login')
def pagos_detalle(request, pago_id):
    """Detalle de solo lectura de un pago realizado: datos del docente/colegio y
    los soportes adjuntos (ver/descargar, sin subir ni eliminar)."""
    pago = get_object_or_404(
        PagoRealizado.objects
        .select_related('profesor', 'colegio__colegio', 'marcado_por')
        .prefetch_related('soportes', 'soportes__subido_por'),
        pk=pago_id,
    )
    return render(request, 'pagos/pago_detalle.html', {'pago': pago})


@user_passes_test(es_personal_programacion, login_url='login')
def soporte_descargar(request, soporte_id):
    """Ver (`?inline=1`) o descargar un soporte de pago desde programación
    (solo lectura). Mismo proxy server-side que financiera; difiere en el gate."""
    soporte = get_object_or_404(SoportePagoProfesor, pk=soporte_id)
    return _responder_soporte(soporte, inline=request.GET.get('inline') == '1')
