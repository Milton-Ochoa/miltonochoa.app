"""
Pagos semanales a profesores (programación, **solo lectura**).

Calcula la liquidación semanal por fila `(profesor, colegio, día)` a partir de las
clases dictadas, la muestra en pestañas pendiente/realizado y la exporta a Excel.
**Marcar el pago y subir/eliminar soportes es de financiera** (financiera/pagos):
aquí solo se ve el listado y el detalle de un pago con sus comprobantes.

Los helpers de cálculo (`construir_contexto_pagos`, `filas_pagos_por_tab`,
`_generar_excel_pagos`, `_semana_label`) son **compartidos**: financiera los importa
para reusar exactamente el mismo cálculo (BD única, sin duplicar lógica).
"""
import io
from datetime import date, datetime, timedelta

from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse
from django.db.models import Count
from django.contrib.auth.decorators import user_passes_test
from core.areas import es_personal_programacion
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from programacion.colegios.models import Clase
from programacion.pagos.models import PagoRealizado, SoportePagoProfesor
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


def _generar_excel_pagos(filas, semana_label):
    """Genera el Excel de pagos con el formato de la imagen."""
    wb = Workbook()
    ws = wb.active
    ws.title = 'Pagos'

    NUM_COLS = 9
    COLS = ['FECHA', 'DOCENTE', 'DOCUMENTO', 'N° DE CUENTA',
            'TIPO DE CUENTA', 'BANCO', 'COLEGIO', 'CODIGO', 'VALOR']

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
    ws.row_dimensions[total_row].height = 22

    # Anchos de columna
    anchos = [12, 22, 14, 18, 18, 16, 30, 10, 14]
    for ci, ancho in enumerate(anchos, start=1):
        ws.column_dimensions[get_column_letter(ci)].width = ancho

    ws.freeze_panes = 'A3'
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def construir_contexto_pagos(get):
    """Arma el contexto de la página semanal de pagos (tabs pendiente/realizado).

    Compartido por la vista de **programación** (solo lectura) y la de **financiera**
    (marcar + soportes), para no duplicar el cálculo de la semana. `get` es un
    `request.GET` (o dict-like con `.get`). Enriquece cada fila realizada con
    `pago_id`, `fecha_pago`, `marcado_por` y `n_soportes` (para el icono de soporte).
    """
    hoy = date.today()
    lunes   = hoy - timedelta(days=hoy.weekday())
    viernes = lunes + timedelta(days=4)
    ayer    = hoy - timedelta(days=1)

    semana_str = get.get('semana', '')
    hasta_str  = get.get('hasta', '')
    if semana_str:
        try:
            lunes = datetime.strptime(semana_str, '%Y-%m-%d').date()
            viernes = (datetime.strptime(hasta_str, '%Y-%m-%d').date()
                       if hasta_str else lunes + timedelta(days=4))
        except ValueError:
            pass
    # Clamp: no permitir fechas futuras
    viernes = min(viernes, ayer)
    lunes   = min(lunes, ayer)

    tab = get.get('tab', 'pendiente')

    pagados_keys = set(
        PagoRealizado.objects
        .filter(fecha__gte=lunes, fecha__lte=viernes)
        .values_list('profesor_id', 'colegio_id', 'fecha')
    )

    todas_filas = _build_filas_pagos(lunes, viernes)
    filas_pendientes, filas_realizadas = [], []
    for f in todas_filas:
        key = (f['profesor_id'], f['colegio_id'], f['fecha'])
        (filas_realizadas if key in pagados_keys else filas_pendientes).append(f)

    # Pagos realizados enriquecidos con fecha_pago, marcado_por y nº de soportes.
    pagos_db = {
        (p.profesor_id, p.colegio_id, p.fecha): p
        for p in PagoRealizado.objects
            .filter(fecha__gte=lunes, fecha__lte=viernes)
            .select_related('marcado_por')
            .annotate(n_soportes=Count('soportes'))
    }
    for f in filas_realizadas:
        pago = pagos_db.get((f['profesor_id'], f['colegio_id'], f['fecha']))
        f['fecha_pago']  = pago.fecha_pago if pago else None
        f['marcado_por'] = (pago.marcado_por.get_full_name() or pago.marcado_por.username) if pago and pago.marcado_por else '—'
        f['pago_id']     = pago.id if pago else None
        f['n_soportes']  = pago.n_soportes if pago else 0

    filas_tab = filas_pendientes if tab == 'pendiente' else filas_realizadas
    return {
        'fecha_inicio':     lunes.isoformat(),
        'fecha_fin':        viernes.isoformat(),
        'fecha_max':        ayer.isoformat(),
        'semana_label':     _semana_label(lunes, viernes),
        'tab':              tab,
        'filas_pendientes': filas_pendientes,
        'filas_realizadas': filas_realizadas,
        'filas':            filas_tab,
        'total_valor':      sum(f['valor_total'] for f in filas_tab),
        'total_pendiente':  sum(f['valor_total'] for f in filas_pendientes),
        'total_realizado':  sum(f['valor_total'] for f in filas_realizadas),
    }


def filas_pagos_por_tab(fecha_inicio, fecha_fin, tab):
    """Devuelve las filas de pago del rango filtradas por el tab activo
    (`'realizado'` = ya tienen `PagoRealizado`; cualquier otro = pendientes).
    Compartido por la descarga de Excel de programación y de financiera."""
    pagados_keys = set(
        PagoRealizado.objects
        .filter(fecha__gte=fecha_inicio, fecha__lte=fecha_fin)
        .values_list('profesor_id', 'colegio_id', 'fecha')
    )
    todas = _build_filas_pagos(fecha_inicio, fecha_fin)
    es_realizado = tab == 'realizado'
    return [f for f in todas
            if ((f['profesor_id'], f['colegio_id'], f['fecha']) in pagados_keys) == es_realizado]


@user_passes_test(es_personal_programacion, login_url='login')
def pagos_lista(request):
    """GET: página de pagos (tabs pendiente/realizado). POST: descarga Excel."""
    hoy = date.today()
    lunes   = hoy - timedelta(days=hoy.weekday())
    viernes = lunes + timedelta(days=4)

    if request.method == 'GET':
        return render(request, 'pagos/pagos.html', construir_contexto_pagos(request.GET))

    # POST: descarga Excel del tab activo
    fi_str = request.POST.get('fecha_inicio', '')
    ff_str = request.POST.get('fecha_fin', '')
    tab    = request.POST.get('tab', 'pendiente')
    try:
        fi = datetime.strptime(fi_str, '%Y-%m-%d').date()
        ff = datetime.strptime(ff_str, '%Y-%m-%d').date()
    except ValueError:
        fi, ff = lunes, viernes

    filas = filas_pagos_por_tab(fi, ff, tab)
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
