import io

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.db import transaction
from django.db.models import ProtectedError
from django.http import HttpResponse
from django.views.decorators.http import require_POST

from openpyxl import Workbook, load_workbook

from core.areas import es_personal_programacion
from programacion.configuracion.colombia_geo import DEPARTAMENTOS, DEPARTAMENTOS_CIUDADES

from .models import ColegioSimulacro, Monitor
from .forms import ColegioSimulacroForm, MonitorForm

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


# ── Colegios de simulacro (catálogo propio, con carga masiva por Excel) ──────

# Columnas esperadas del Excel de carga masiva, en orden. La carga es tolerante
# al orden/mayúsculas de los encabezados: se mapean por nombre normalizado.
_COLS_CARGA = ['nombre', 'codigo', 'ciudad', 'departamento']
# Tamaño máximo del .xlsx subido (5 MB; un catálogo de colegios no pesa más).
_MAX_XLSX_BYTES = 5 * 1024 * 1024


def _norm(texto):
    """Normaliza un encabezado/celda a str limpio (sin espacios, en minúsculas
    para los encabezados). Acepta None y números (openpyxl puede leer códigos
    numéricos como int)."""
    if texto is None:
        return ''
    return str(texto).strip()


@solo_personal
def configuracion_colegios_simulacro(request):
    """Catálogo de colegios de simulacro — CRUD + carga masiva por Excel.

    Es un catálogo independiente de ``configuracion.Colegio`` (los simulacros se
    hacen en instituciones que no están en el sistema). Acciones POST: add, edit,
    toggle_activo, del, cargar (Excel).
    """
    if request.method == 'POST':
        accion = request.POST.get('accion', 'add')

        if accion == 'edit':
            c    = get_object_or_404(ColegioSimulacro, id=request.POST.get('colegio_id'))
            form = ColegioSimulacroForm(request.POST, instance=c)
            if form.is_valid():
                form.save()
                messages.success(request, 'Colegio actualizado.')
            else:
                messages.error(request, 'No se pudo guardar: revisa los datos.')

        elif accion == 'toggle_activo':
            c = get_object_or_404(ColegioSimulacro, id=request.POST.get('colegio_id'))
            c.activo = not c.activo
            c.save(update_fields=['activo'])

        elif accion == 'del':
            c_del = ColegioSimulacro.objects.filter(id=request.POST.get('colegio_id')).first()
            if c_del:
                try:
                    c_del.delete()
                    messages.success(request, 'Colegio eliminado.')
                except ProtectedError:
                    # En la Fase 3 los simulacros usarán PROTECT/SET_NULL.
                    messages.error(
                        request,
                        'No se puede eliminar el colegio: tiene simulacros asociados.'
                    )

        elif accion == 'cargar':
            _cargar_colegios_excel(request)

        else:  # add
            form = ColegioSimulacroForm(request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, 'Colegio creado.')
            else:
                messages.error(request, 'No se pudo crear: revisa los datos.')

        return redirect('configuracion_colegios_simulacro')

    colegios = ColegioSimulacro.objects.order_by('nombre')

    return render(request, 'monitores/configuracion_colegios_simulacro.html', {
        'colegios':           colegios,
        'departamentos':      DEPARTAMENTOS,
        'departamentos_json': DEPARTAMENTOS_CIUDADES,
    })


def _cargar_colegios_excel(request):
    """Lee el .xlsx subido y crea colegios con ``get_or_create`` por nombre
    normalizado (idempotente: re-subir el mismo archivo no duplica). Reporta por
    ``messages`` cuántos se crearon / omitieron / fallaron. Tolerante: nunca
    lanza, todo error se vuelve un mensaje."""
    archivo = request.FILES.get('archivo')
    if not archivo:
        messages.error(request, 'No se adjuntó ningún archivo.')
        return
    if not archivo.name.lower().endswith('.xlsx'):
        messages.error(request, 'El archivo debe ser un Excel (.xlsx).')
        return
    if archivo.size > _MAX_XLSX_BYTES:
        messages.error(request, 'El archivo supera el tamaño máximo (5 MB).')
        return

    try:
        wb = load_workbook(archivo, read_only=True, data_only=True)
        ws = wb.active
        filas = ws.iter_rows(values_only=True)
        encabezados = next(filas, None)
    except Exception:
        messages.error(request, 'No se pudo leer el Excel: ¿está dañado o vacío?')
        return

    if not encabezados:
        messages.error(request, 'El Excel está vacío.')
        return

    # Mapa encabezado-normalizado → índice de columna (tolera orden/mayúsculas).
    indices = {}
    for i, cab in enumerate(encabezados):
        clave = _norm(cab).lower()
        if clave in _COLS_CARGA:
            indices[clave] = i
    if 'nombre' not in indices:
        messages.error(
            request,
            'El Excel no tiene la columna obligatoria "nombre". '
            'Descarga la plantilla para ver el formato esperado.')
        return

    def celda(fila, col):
        idx = indices.get(col)
        return _norm(fila[idx]) if idx is not None and idx < len(fila) else ''

    creados = omitidos = vacios = 0
    nuevos = []
    vistos = set()  # nombres ya procesados en este archivo (dedupe interno)
    existentes = {n.lower() for n in
                  ColegioSimulacro.objects.values_list('nombre', flat=True)}

    for fila in filas:
        if not fila:
            continue
        nombre = celda(fila, 'nombre')
        if not nombre:
            vacios += 1
            continue
        clave = nombre.lower()
        if clave in existentes or clave in vistos:
            omitidos += 1
            continue
        vistos.add(clave)
        nuevos.append(ColegioSimulacro(
            nombre=nombre,
            codigo=celda(fila, 'codigo') or None,
            ciudad=celda(fila, 'ciudad') or None,
            departamento=celda(fila, 'departamento') or None,
        ))
        creados += 1

    if nuevos:
        with transaction.atomic():
            ColegioSimulacro.objects.bulk_create(nuevos)

    partes = [f'{creados} creado(s)']
    if omitidos:
        partes.append(f'{omitidos} omitido(s) por ya existir')
    if vacios:
        partes.append(f'{vacios} fila(s) sin nombre ignorada(s)')
    if creados:
        messages.success(request, 'Carga masiva: ' + ', '.join(partes) + '.')
    else:
        messages.warning(request, 'Carga masiva: ' + ', '.join(partes) + '.')


@require_POST
@solo_personal
def colegios_simulacro_plantilla(request):
    """Descarga una plantilla .xlsx vacía con los encabezados esperados por la
    carga masiva, para que el usuario sepa el formato exacto."""
    wb = Workbook()
    ws = wb.active
    ws.title = 'Colegios'
    ws.append(['nombre', 'codigo', 'ciudad', 'departamento'])
    # Fila de ejemplo (orientativa).
    ws.append(['Colegio San José', 'CSJ-001', 'Bucaramanga', 'Santander'])
    for col, ancho in zip('ABCD', (32, 14, 20, 20)):
        ws.column_dimensions[col].width = ancho
    buf = io.BytesIO()
    wb.save(buf)
    response = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename="plantilla_colegios_simulacro.xlsx"'
    return response
