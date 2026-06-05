from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.http import JsonResponse, HttpResponse
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.cache import cache
from django.conf import settings
from django.db import transaction, IntegrityError
from django.db.models import Q
from datetime import date, timedelta, datetime
from collections import defaultdict
import calendar as _calendar
import json
import logging
import threading

from programacion.configuracion.models import Colegio, ColegioAnio, Profesor, NombreLibro, Unidad, Materia
from .models import Bloque, Clase, Asignacion, Grado, HistorialCambio
from .historial import registrar_cambio, aplicar_filtros_historial
from .utils import extraer_numero_grado, ordenar_grados
from usuarios.ratelimit import rate_limit

logger = logging.getLogger('aamo')

_STATS_CACHE_TTL = 120  # segundos
_MATRIZ_CACHE_TTL = 120  # segundos


def _stats_cache_key(colegio_id, anio):
    return f'dashboard_stats:{colegio_id}:{anio}'


def _matriz_cache_key(colegio_id, anio):
    return f'dashboard_matriz:{colegio_id}:{anio}'


@login_required
def cargar_grados(request):
    """Retorna los grados activos con bloques en un ColegioAnio (para poblar selects dinámicos)."""
    colegio_id = request.GET.get('colegio_id')
    if colegio_id:
        grados = (
            Bloque.objects
            .filter(colegio_id=colegio_id)
            .values_list('grado__nombre', flat=True)
            .distinct()
        )
        return JsonResponse(list(grados), safe=False)
    return JsonResponse([], safe=False)


@login_required
@rate_limit(max_calls=200, periodo=60)
def obtener_materias(request):
    """
    Retorna las materias disponibles según el contexto del modal de clase.

    Tres rutas de resolución (en orden de prioridad):
      1. ?todas=1  → todas las materias del sistema (para socializaciones)
      2. ?libro_id=X → materias del libro específico (para material asignado)
      3. ?colegio_id + grado + fecha → materias del libro asignado al grado en esa fecha

    El campo `sin_libro` en la respuesta indica si el grado no tiene asignación
    vigente para la fecha dada, para que el frontend pueda mostrar un aviso.
    """
    colegio_id = request.GET.get('colegio_id')
    grado      = request.GET.get('grado')
    fecha_str  = request.GET.get('fecha')

    if request.GET.get('todas') == '1':
        materias = sorted(Materia.objects.values_list('nombre', flat=True))
        return JsonResponse({'materias': materias, 'sin_libro': False})

    libro_id = request.GET.get('libro_id')
    if libro_id:
        materias = sorted(set(
            Unidad.objects.filter(libro_id=libro_id)
            .exclude(materia__nombre__isnull=True)
            .values_list('materia__nombre', flat=True)
        ))
        return JsonResponse({'materias': materias, 'sin_libro': False})

    if not all([colegio_id, grado, fecha_str]):
        return JsonResponse([], safe=False)

    try:
        fecha_clase = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse([], safe=False)

    libros_ids = list(Asignacion.objects.filter(
        colegio_id=colegio_id,
        grado__nombre=grado,
        fecha_inicio__lte=fecha_clase,
        fecha_fin__gte=fecha_clase,
        libro__isnull=False,
    ).values_list('libro_id', flat=True))

    materias = list(
        NombreLibro.objects.filter(id__in=libros_ids)
        .values_list('unidades__materia__nombre', flat=True)
        .distinct()
    )
    materias = [m for m in materias if m]

    libro_nombre = None
    if libros_ids:
        libro_obj = NombreLibro.objects.filter(id__in=libros_ids).first()
        if libro_obj:
            libro_nombre = libro_obj.nombre

    return JsonResponse({
        'materias':    sorted(set(materias)),
        'sin_libro':   len(libros_ids) == 0,
        'libro_nombre': libro_nombre,
    })


@login_required
def ajax_obtener_libros_especiales(request):
    """Retorna solo los libros marcados como 'Material Asignado' (para el modal de clase)."""
    libros = list(
        NombreLibro.objects.filter(activo=True, es_material_asignado=True)
        .order_by('nombre')
        .values('id', 'nombre')
    )
    return JsonResponse(libros, safe=False)


@login_required
@rate_limit(max_calls=200, periodo=60)
def obtener_unidades(request):
    """
    Retorna las unidades disponibles para una materia y recomienda la siguiente a programar.

    La recomendación sigue la regla: max(unidades ya dictadas) + 1, o la unidad 1
    si no hay historial. Se limita al rango de la asignación vigente para reiniciar
    el contador correctamente cuando el grado cambia de libro a mitad de año.

    Para libros especiales (libro_id param) el historial se filtra también por
    libro_especial_id, evitando mezclar conteos entre libros distintos del mismo material.

    El bloque_id se excluye del historial cuando la fecha es la actual, para que
    editar una clase existente no cuente esa clase como "ya dictada".
    """
    colegio_id    = request.GET.get('colegio_id')
    grado         = request.GET.get('grado')
    fecha_str     = request.GET.get('fecha')
    materia       = request.GET.get('materia')
    bloque_id     = request.GET.get('bloque_id')
    libro_id_esp  = request.GET.get('libro_id')

    if not materia:
        return JsonResponse({'unidades': [], 'recomendada': '', 'links': {}})

    if libro_id_esp:
        rows = (
            Unidad.objects
            .filter(libro_id=libro_id_esp, materia__nombre=materia)
            .order_by('numero')
            .values('numero', 'link')
        )
        unidades_finales = []
        links = {}
        for r in rows:
            n = str(r['numero'])
            unidades_finales.append(n)
            links[n] = r['link'] or ''

        # Recomendación: última clase de este colegio/grado/materia/libro_especial
        unidad_recomendada = ''
        if colegio_id and grado and fecha_str:
            try:
                fecha_clase = datetime.strptime(fecha_str, '%Y-%m-%d').date()
            except ValueError:
                fecha_clase = None
            if fecha_clase:
                q = Clase.objects.filter(
                    colegio_id=colegio_id,
                    bloque__grado__nombre=grado,
                    materia__nombre=materia,
                    libro_especial_id=libro_id_esp,
                    fecha__lte=fecha_clase,
                )
                if bloque_id:
                    q = q.exclude(bloque_id=bloque_id, fecha=fecha_clase)
                ultima = q.order_by('-fecha', '-bloque__hora_inicio', '-id').first()
                if ultima and ultima.unidad and str(ultima.unidad).isdigit():
                    siguiente = str(int(ultima.unidad) + 1)
                    unidad_recomendada = siguiente if siguiente in unidades_finales else ''
                elif unidades_finales:
                    unidad_recomendada = unidades_finales[0]

        return JsonResponse({'unidades': unidades_finales, 'recomendada': unidad_recomendada, 'links': links})

    if not all([colegio_id, grado, fecha_str]):
        return JsonResponse({'unidades': [], 'recomendada': '', 'links': {}})

    try:
        fecha_clase = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'unidades': [], 'recomendada': '', 'links': {}})

    asignaciones_qs = Asignacion.objects.filter(
        colegio_id=colegio_id,
        grado__nombre=grado,
        fecha_inicio__lte=fecha_clase,
        fecha_fin__gte=fecha_clase,
    )
    libros_ids = asignaciones_qs.values_list('libro_id', flat=True)

    rows = (
        Unidad.objects
        .filter(libro_id__in=libros_ids, materia__nombre=materia)
        .values('numero', 'link')
    )
    links = {}
    nums = set()
    for r in rows:
        n = str(r['numero'])
        if n.isdigit():
            nums.add(n)
            links[n] = r['link'] or ''

    unidades_finales = sorted(nums, key=int)

    unidad_recomendada = ''
    # Limitar búsqueda al rango de la asignación vigente para reiniciar el conteo al cambiar de libro
    asignacion_actual = asignaciones_qs.filter(libro__isnull=False).first()

    query_clases = Clase.objects.filter(
        colegio_id=colegio_id,
        bloque__grado__nombre=grado,
        materia__nombre=materia,
        fecha__lte=fecha_clase,
        libro_especial__isnull=True,
    ).exclude(unidad='S')

    if asignacion_actual:
        query_clases = query_clases.filter(fecha__gte=asignacion_actual.fecha_inicio)
    if bloque_id:
        query_clases = query_clases.exclude(bloque_id=bloque_id, fecha=fecha_clase)

    ultima_clase = query_clases.order_by('-fecha', '-bloque__hora_inicio', '-id').first()
    if ultima_clase and ultima_clase.unidad and str(ultima_clase.unidad).isdigit():
        siguiente = str(int(ultima_clase.unidad) + 1)
        if siguiente in unidades_finales:
            unidad_recomendada = siguiente
    elif unidades_finales:
        unidad_recomendada = unidades_finales[0]

    return JsonResponse({'unidades': unidades_finales, 'recomendada': unidad_recomendada, 'links': links})


# ─────────────────────────────────────────────────────────────
# HELPERS PRIVADOS
# ─────────────────────────────────────────────────────────────
def _guardar_clase(request, sel_col):
    """
    Guarda (create/update/delete) una clase a partir del POST del modal de clase.

    Retorna una lista `recalcular` con los rangos a renumerar (puede estar vacía).
    Cada elemento tiene: {grado, materia, unidad_inicio, fecha_desde, bloque_excluir,
    n_clases, motivo}. El llamador (ajax_guardar_clase) lo devuelve al frontend
    para que muestre el modal de confirmación de recálculo.

    La detección de recálculo solo aplica a clases normales (no eventos, no canceladas,
    unidad numérica). Si cambia la materia, se ofrece renumerar la materia vieja
    (motivo='materia_quitada') y también la nueva (motivo='continuacion').

    _futuras() usa fecha__gte en el mismo día + exclude(bloque_id) para capturar
    clases en otros bloques del mismo día sin incluir la clase que se está guardando.
    """
    bloque_id   = request.POST.get('bloque_id')
    fecha_clase = request.POST.get('fecha_clase')

    # Validar que la fecha pertenezca a la ventana real del periodo (calendario A/B)
    if fecha_clase:
        try:
            fecha_obj = datetime.strptime(fecha_clase, '%Y-%m-%d').date()
            inicio, fin = sel_col.rango
            if not (inicio <= fecha_obj <= fin):
                messages.error(
                    request,
                    f'La fecha {fecha_clase} no corresponde al periodo '
                    f'{sel_col.periodo_label} del colegio.'
                )
                return
        except ValueError:
            pass

    if request.POST.get('eliminar_clase') == '1':
        clase_a_eliminar = Clase.objects.filter(
            colegio=sel_col, bloque_id=bloque_id, fecha=fecha_clase
        ).first()
        if clase_a_eliminar:
            registrar_cambio(request, 'eliminar', clase_a_eliminar, colegio=sel_col)
        Clase.objects.filter(
            colegio=sel_col, bloque_id=bloque_id, fecha=fecha_clase
        ).delete()
        return

    profesor_id = request.POST.get('profesor') or None
    materia_nombre = request.POST.get('materia')
    materia_obj = None
    if materia_nombre:
        materia_obj, _ = Materia.objects.get_or_create(nombre=materia_nombre)

    # Material especial (unidad S o libro no asignado)
    material_especial = request.POST.get('material_especial') == '1'
    if material_especial:
        tipo_especial = request.POST.get('tipo_especial', '')
        if tipo_especial == 'socializacion':
            unidad_valor = 'S'
            libro_especial_obj = None
        else:
            # Se guarda el número de unidad real (no 'A')
            unidad_valor = request.POST.get('unidad')
            libro_especial_id = request.POST.get('libro_especial_id') or None
            libro_especial_obj = (
                NombreLibro.objects.filter(id=libro_especial_id).first()
                if libro_especial_id else None
            )
        enlace_personalizado = request.POST.get('enlace_personalizado') or None
    else:
        unidad_valor = request.POST.get('unidad')
        libro_especial_obj = None
        enlace_personalizado = None

    # Capturar estado anterior para detectar cambios que afecten la secuencia
    clase_anterior = Clase.objects.filter(
        colegio=sel_col, bloque_id=bloque_id, fecha=fecha_clase
    ).select_related('materia', 'bloque__grado').first()
    old_materia       = clase_anterior.materia.nombre if (clase_anterior and clase_anterior.materia) else None
    old_unidad        = clase_anterior.unidad if clase_anterior else None
    old_es_evento     = bool(clase_anterior.es_evento) if clase_anterior else False
    old_es_cancelada  = bool(clase_anterior.cancelada) if clase_anterior else False
    old_libro_esp_id  = clase_anterior.libro_especial_id if clase_anterior else None

    clase, created = Clase.objects.update_or_create(
        colegio=sel_col,
        bloque_id=bloque_id,
        fecha=fecha_clase,
        defaults={
            'profesor_id':        profesor_id,
            'materia':            materia_obj,
            'unidad':             unidad_valor,
            'libro_especial':     libro_especial_obj,
            'enlace_personalizado': enlace_personalizado,
            'es_evento':          request.POST.get('es_evento') == 'on',
            'titulo_evento':      request.POST.get('titulo_evento'),
            'cancelada':          request.POST.get('cancelada') == 'on',
            'comentarios':        request.POST.get('comentarios'),
        }
    )
    logger.info(f'Clase guardada: {clase} colegio={sel_col} (por {request.user.username})')
    registrar_cambio(
        request,
        'crear' if created else 'editar',
        clase,
        colegio=sel_col,
    )

    # Detectar si se debe ofrecer recalcular secuencias.
    # Una clase "regular" es la que cuenta en la numeración secuencial de su materia:
    # no evento, no cancelada, sin libro_especial (no material asignado), unidad numérica
    # distinta de 'S' (no socialización), con materia asignada.
    # Si la regularidad o la (materia, unidad) cambió respecto al estado anterior, las
    # clases futuras de la(s) materia(s) afectada(s) pueden necesitar renumerarse.
    es_evento    = request.POST.get('es_evento') == 'on'
    es_cancelada = request.POST.get('cancelada') == 'on'
    new_materia  = materia_obj.nombre if materia_obj else None
    new_unidad   = unidad_valor
    new_libro_esp_id = libro_especial_obj.id if libro_especial_obj else None

    def _es_regular(es_ev, es_can, libro_esp_id, unidad, materia_nombre):
        if es_ev or es_can:
            return False
        if libro_esp_id is not None:
            return False
        if not materia_nombre:
            return False
        if not unidad or str(unidad) == 'S' or not str(unidad).isdigit():
            return False
        return True

    old_regular = (clase_anterior is not None) and _es_regular(
        old_es_evento, old_es_cancelada, old_libro_esp_id, old_unidad, old_materia,
    )
    new_regular = _es_regular(
        es_evento, es_cancelada, new_libro_esp_id, new_unidad, new_materia,
    )

    recalcular = []
    if old_regular or new_regular:
        bloque_obj   = Bloque.objects.select_related('grado').get(id=bloque_id)
        grado_nombre = bloque_obj.grado.nombre
        fecha_obj    = datetime.strptime(fecha_clase, '%Y-%m-%d').date() if isinstance(fecha_clase, str) else fecha_clase
        hora_inicio_bloque = bloque_obj.hora_inicio

        # Determinar el libro vigente en (grado, fecha) para no renumerar clases que
        # caen en otra Asignacion (otro libro). El rango de fechas se toma del registro
        # de Asignacion (cualquier partición: ene-jun/jul-dic, ene-ago/sep-dic, varios
        # libros sucesivos, etc.). Si no hay Asignacion (datos sin configurar), se hace
        # fallback al comportamiento previo (sin tope superior de fecha).
        asig_actual = Asignacion.objects.filter(
            colegio=sel_col,
            grado__nombre=grado_nombre,
            fecha_inicio__lte=fecha_obj,
            fecha_fin__gte=fecha_obj,
        ).first()
        fecha_hasta = asig_actual.fecha_fin if asig_actual else None

        def _futuras(materia_nombre):
            """
            Cuenta clases futuras renumerables de una materia desde el bloque editado,
            acotadas al rango de la Asignacion vigente (mismo libro).

            Incluye: clases posteriores a la fecha, y clases del mismo día en bloques
            con hora_inicio posterior (para no renumerar bloques anteriores del mismo día).
            Excluye: el bloque que se acaba de guardar (bloque_id, fecha_obj).
            """
            qs = Clase.objects.filter(
                Q(fecha__gt=fecha_obj) |
                Q(fecha=fecha_obj, bloque__hora_inicio__gt=hora_inicio_bloque),
                colegio=sel_col,
                bloque__grado__nombre=grado_nombre,
                materia__nombre=materia_nombre,
                es_evento=False,
                cancelada=False,
                libro_especial__isnull=True,
            ).exclude(unidad='S')
            if fecha_hasta:
                qs = qs.filter(fecha__lte=fecha_hasta)
            return qs.count()

        misma_materia = old_regular and new_regular and old_materia == new_materia
        misma_unidad  = misma_materia and str(old_unidad) == str(new_unidad)

        # La materia vieja "pierde" esta clase si: (a) antes era regular y ahora no,
        # o (b) cambió de materia. Renumerar futuras desde old_unidad.
        materia_quitada = old_regular and (not new_regular or old_materia != new_materia)
        if materia_quitada and old_materia and str(old_unidad).isdigit():
            n = _futuras(old_materia)
            if n > 0:
                recalcular.append({
                    'grado':         grado_nombre,
                    'materia':       old_materia,
                    'unidad_inicio': int(old_unidad),
                    'fecha_desde':   fecha_obj.isoformat(),
                    'bloque_excluir': str(bloque_id),
                    'n_clases':      n,
                    'motivo':        'materia_quitada',
                })

        # La materia nueva "gana" esta clase (o cambió de unidad) si la clase actual
        # es regular y la (materia, unidad) difiere del estado anterior. Continuación
        # desde new_unidad+1. Si solo cambió el profesor / comentarios, no se ofrece.
        continuacion = new_regular and not misma_unidad
        if continuacion:
            n = _futuras(new_materia)
            if n > 0:
                recalcular.append({
                    'grado':         grado_nombre,
                    'materia':       new_materia,
                    'unidad_inicio': int(new_unidad) + 1,
                    'fecha_desde':   fecha_obj.isoformat(),
                    'bloque_excluir': str(bloque_id),
                    'n_clases':      n,
                    'motivo':        'continuacion',
                })

    return recalcular


def _calcular_enlace_efectivo(clase):
    """Asigna clase.enlace_efectivo (atributo dinámico) para una sola instancia."""
    if (clase.libro_especial_id and clase.materia_id
            and clase.unidad and str(clase.unidad).isdigit()):
        link = (
            Unidad.objects
            .filter(
                libro_id=clase.libro_especial_id,
                materia_id=clase.materia_id,
                numero=int(clase.unidad),
            )
            .values_list('link', flat=True)
            .first()
        ) or ''
        clase.enlace_efectivo = link or clase.enlace_personalizado or ''
    else:
        clase.enlace_efectivo = clase.enlace_personalizado or ''


@login_required
def ajax_guardar_clase(request, colegio_id):
    """
    Guarda/elimina clase vía AJAX.

    Modo dual:
    - Si la petición lleva HX-Request (HTMX o fetch con ese header):
        retorna el fragmento HTML de la celda actualizada + HX-Trigger para
        toasts y datos de recálculo. Sin recarga de página.
    - Si no: retorna JSON legacy (compatibilidad con código antiguo).
    """
    if not request.es_personal_programacion:
        return JsonResponse({'error': 'Sin permiso'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    sel_col = get_object_or_404(ColegioAnio, id=colegio_id)
    is_htmx = bool(request.META.get('HTTP_HX_REQUEST'))

    fecha_clase = request.POST.get('fecha_clase')
    bloque_id   = request.POST.get('bloque_id')

    if fecha_clase:
        try:
            fecha_obj = datetime.strptime(fecha_clase, '%Y-%m-%d').date()
            inicio, fin = sel_col.rango
            if not (inicio <= fecha_obj <= fin):
                err = f'Fecha fuera del periodo {sel_col.periodo_label}'
                if is_htmx:
                    resp = HttpResponse(status=400)
                    resp['HX-Trigger'] = json.dumps({'showToast': {'msg': err, 'level': 'danger'}})
                    return resp
                return JsonResponse({'error': err}, status=400)
        except ValueError:
            if is_htmx:
                resp = HttpResponse(status=400)
                resp['HX-Trigger'] = json.dumps({'showToast': {'msg': 'Fecha inválida', 'level': 'danger'}})
                return resp
            return JsonResponse({'error': 'Fecha inválida'}, status=400)

    if request.POST.get('eliminar_clase') == '1':
        clase_a_eliminar = Clase.objects.filter(
            colegio=sel_col, bloque_id=bloque_id, fecha=fecha_clase,
        ).first()
        if clase_a_eliminar:
            registrar_cambio(request, 'eliminar', clase_a_eliminar, colegio=sel_col)
        Clase.objects.filter(
            colegio=sel_col, bloque_id=bloque_id, fecha=fecha_clase,
        ).delete()
        cache.delete(_stats_cache_key(sel_col.id, sel_col.anio))
        cache.delete(_matriz_cache_key(sel_col.id, sel_col.anio))
        if is_htmx:
            resp = HttpResponse('')  # celda vacía
            resp['HX-Trigger'] = json.dumps({'showToast': {'msg': 'Clase eliminada', 'level': 'warning'}})
            return resp
        return JsonResponse({'ok': True, 'eliminada': True, 'recalcular': []})

    recalcular = _guardar_clase(request, sel_col)
    cache.delete(_stats_cache_key(sel_col.id, sel_col.anio))

    if is_htmx:
        clase = (
            Clase.objects
            .select_related('profesor', 'libro_especial', 'materia')
            .filter(colegio=sel_col, bloque_id=bloque_id, fecha=fecha_clase)
            .first()
        )
        if clase:
            _calcular_enlace_efectivo(clase)
        triggers = {'showToast': {'msg': 'Clase guardada', 'level': 'success'}}
        if recalcular:
            triggers['recalcular'] = recalcular
        resp = render(request, 'colegios/_partials/_bloque_celda.html', {
            'clase':      clase,
            'bloque_id':  bloque_id,
            'fecha_str':  fecha_clase,
            'is_staff':   request.es_personal_programacion,
        })
        resp['HX-Trigger'] = json.dumps(triggers)
        return resp

    return JsonResponse({'ok': True, 'recalcular': recalcular or []})


@login_required
def ajax_recalcular_secuencia(request, colegio_id):
    """
    Renumera secuencialmente las clases futuras de un grado+materia desde unidad_inicio.

    Filtra clases normales (no eventos, no canceladas, no material especial, no 'S')
    a partir de fecha_desde, excluyendo el bloque recién editado para no pisar la
    clase que disparó el recálculo. Ordena por (fecha, hora_inicio) para garantizar
    una numeración cronológica correcta. Usa bulk_update para evitar N queries.
    """
    if not request.es_personal_programacion:
        return JsonResponse({'error': 'Sin permiso'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    sel_col       = get_object_or_404(ColegioAnio, id=colegio_id)
    grado         = request.POST.get('grado')
    materia       = request.POST.get('materia')
    fecha_desde   = request.POST.get('fecha_desde')
    unidad_inicio = request.POST.get('unidad_inicio')
    bloque_excluir_raw = request.POST.get('bloque_excluir')
    try:
        bloque_excluir = int(bloque_excluir_raw) if bloque_excluir_raw else None
    except (ValueError, TypeError):
        bloque_excluir = None

    if not all([grado, materia, fecha_desde, unidad_inicio]):
        return JsonResponse({'error': 'Parámetros incompletos'}, status=400)

    try:
        unidad_inicio = int(unidad_inicio)
        fecha_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Parámetros inválidos'}, status=400)

    # Determinar hora de referencia para filtrar mismo día con precisión horaria
    hora_ref = None
    if bloque_excluir:
        try:
            hora_ref = Bloque.objects.values_list('hora_inicio', flat=True).get(id=bloque_excluir)
        except Bloque.DoesNotExist:
            pass

    if hora_ref is not None:
        qs = Clase.objects.filter(
            Q(fecha__gt=fecha_obj) |
            Q(fecha=fecha_obj, bloque__hora_inicio__gt=hora_ref),
            colegio=sel_col,
            bloque__grado__nombre=grado,
            materia__nombre=materia,
            es_evento=False,
            cancelada=False,
            libro_especial__isnull=True,
        ).exclude(unidad='S')
    else:
        qs = Clase.objects.filter(
            colegio=sel_col,
            bloque__grado__nombre=grado,
            materia__nombre=materia,
            fecha__gte=fecha_obj,
            es_evento=False,
            cancelada=False,
            libro_especial__isnull=True,
        ).exclude(unidad='S')

    # Acotar al rango de la Asignacion vigente en (grado, fecha_desde) para no pisar
    # las clases del siguiente libro asignado al mismo grado en el año.
    asig_actual = Asignacion.objects.filter(
        colegio=sel_col,
        grado__nombre=grado,
        fecha_inicio__lte=fecha_obj,
        fecha_fin__gte=fecha_obj,
    ).first()
    if asig_actual:
        qs = qs.filter(fecha__lte=asig_actual.fecha_fin)

    clases = list(qs.order_by('fecha', 'bloque__hora_inicio'))

    for i, c in enumerate(clases):
        c.unidad = str(unidad_inicio + i)
    Clase.objects.bulk_update(clases, ['unidad'])

    logger.info(f'Recálculo secuencia: {len(clases)} clases de {materia}/{grado} desde {fecha_desde} (por {request.user.username})')
    return JsonResponse({'ok': True, 'actualizadas': len(clases)})


def _construir_bloques_agrupados(sel_col):
    """
    Retorna (bloques_raw, dict grado→lista de Bloques ordenados por hora_inicio).

    `bloques_raw` se pasa a `_construir_matriz` para construir el dict de IDs;
    el dict agrupado va al contexto del template para renderizar las cabeceras.
    Los grados se ordenan con `ordenar_grados` (tradicionales desc, especiales al final).
    """
    bloques_raw = Bloque.objects.filter(colegio=sel_col).select_related('grado')
    bloques_temp = defaultdict(list)
    for b in bloques_raw:
        bloques_temp[b.grado.nombre].append(b)

    grados_ordenados = ordenar_grados(bloques_temp.keys())
    return bloques_raw, {
        grado: sorted(bloques_temp[grado], key=lambda x: x.hora_inicio)
        for grado in grados_ordenados
    }


def _construir_matriz(sel_col, bloques_raw, inicio, fin):
    """
    Construye la matriz {bloque_id: {fecha_str: Clase}} para el template del dashboard.

    Estrategia N+1:
    - Clases con libro_especial necesitan el link de la unidad correspondiente.
    - En lugar de llamar a c.libro_especial.unidades.filter(...) dentro del loop
      (N queries), se pre-carga en batch todos los links de los libros especiales
      usados y se asigna c.enlace_efectivo como atributo dinámico.
    - Se usa atributo plano (no @property) para poder asignar desde fuera sin setter.
    - Nombre sin _ inicial para que sea accesible desde templates (Django rechaza _vars).
    """
    clases = list(
        Clase.objects.filter(
            colegio=sel_col, fecha__range=[inicio, fin]
        ).select_related('profesor', 'libro_especial', 'materia')
    )

    # Precomputar enlaces para clases con libro_especial (evita N+1 queries)
    libros_ids = {c.libro_especial_id for c in clases if c.libro_especial_id}
    unidades_links = {}  # {(libro_id, materia_id, numero): link}
    if libros_ids:
        for u in Unidad.objects.filter(libro_id__in=libros_ids).values('libro_id', 'materia_id', 'numero', 'link'):
            unidades_links[(u['libro_id'], u['materia_id'], u['numero'])] = u['link'] or ''

    for c in clases:
        if c.libro_especial_id and c.materia_id and c.unidad and str(c.unidad).isdigit():
            key = (c.libro_especial_id, c.materia_id, int(c.unidad))
            unidad_link = unidades_links.get(key, '')
            c.enlace_efectivo = unidad_link or c.enlace_personalizado or ''
        else:
            c.enlace_efectivo = c.enlace_personalizado or ''

    matriz = {b.id: {} for b in bloques_raw}
    for c in clases:
        if c.bloque_id in matriz:
            matriz[c.bloque_id][str(c.fecha)] = c
    return matriz


def _construir_stats(sel_col):
    """
    Construye el JSON de estadísticas de avance curricular por grado/materia/libro.

    Retorna un dict: {grado: {materia: {color, libros, detalle_adicional}}}

    Pipeline en 4 pasos:
      1. Universo: qué unidades debería tener cada (grado, materia, libro) según
         las Asignaciones activas. Base de comparación para marcar pendientes/inválidos.
      2. Conteo + detalle: cuántas veces se dictó cada unidad. Excluye socializaciones
         ('S') y materiales asignados (libro_especial != null) — éstos van a paso 3.
      3. Adicionales: clases de tipo S o material asignado, separadas del currículo normal.
      4. Pre-indexación con defaultdict (O(1)) antes del loop de ensamblado final,
         que de otra forma sería O(n×m) al cruzar universo con conteo por cada grado.

    Estados de unidad: 'dado' (cnt=1), 'repetido' (cnt>1), 'pendiente' (cnt=0),
    'invalido' (en conteo pero fuera del universo del libro asignado).

    Meses en español via _MESES_ES — no strftime (Render no tiene locale es configurado).
    """
    MESES_ES = ['', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
                'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

    def _fecha_display(d):
        return f"{d.day} {MESES_ES[d.month]}"

    colores      = {}  # materia_nombre -> color hex
    libros_nombre = {}  # libro_id -> nombre del libro

    # 1. Universo de unidades por (grado, materia, libro_id) + mapa de asignaciones por grado
    universo = defaultdict(set)           # (grado, materia, libro_id) -> set de str(numero)
    asignaciones_por_grado = defaultdict(list)  # grado_nombre -> [(fecha_inicio, fecha_fin, libro_id)]

    asignaciones = (
        Asignacion.objects
        .filter(colegio=sel_col, libro__isnull=False)
        .select_related('grado', 'libro')
        .prefetch_related('libro__unidades__materia')
    )
    for a in asignaciones:
        grado_nombre = a.grado.nombre
        libros_nombre[a.libro_id] = a.libro.nombre
        asignaciones_por_grado[grado_nombre].append(
            (a.fecha_inicio, a.fecha_fin, a.libro_id)
        )
        for u in a.libro.unidades.all():
            materia_nombre = u.materia.nombre
            universo[(grado_nombre, materia_nombre, a.libro_id)].add(str(u.numero))
            colores[materia_nombre] = u.materia.color

    # Sort by fecha_inicio so _libro_de_clase is deterministic when assignments overlap.
    for grado_nombre in asignaciones_por_grado:
        asignaciones_por_grado[grado_nombre].sort(key=lambda t: t[0] or date.min)

    def _libro_de_clase(grado_nombre, fecha):
        """Devuelve el libro_id de la asignación vigente para esa fecha, o None."""
        for fi, ff, lid in asignaciones_por_grado.get(grado_nombre, []):
            if fi and ff and fi <= fecha <= ff:
                return lid
        return None

    # 2. Conteo y detalle de clases normales (excluye S y material asignado), separado por libro
    conteo  = defaultdict(int)   # (grado, materia, libro_id, unidad_str) -> int
    detalle = defaultdict(list)  # (grado, materia, libro_id) -> lista de dicts

    clases = (
        Clase.objects
        .filter(
            colegio=sel_col,
            cancelada=False,
            es_evento=False,
            materia__isnull=False,
            unidad__isnull=False,
        )
        .exclude(unidad='')
        .exclude(unidad='S')
        .exclude(libro_especial__isnull=False)
        .select_related('bloque__grado', 'materia', 'profesor')
        .order_by('fecha')
    )
    for c in clases:
        grado_nombre   = c.bloque.grado.nombre
        materia_nombre = c.materia.nombre
        unidad_str     = str(c.unidad)
        colores[materia_nombre] = c.materia.color
        lid = _libro_de_clase(grado_nombre, c.fecha)
        conteo[(grado_nombre, materia_nombre, lid, unidad_str)] += 1
        detalle[(grado_nombre, materia_nombre, lid)].append({
            'fecha':         c.fecha.isoformat(),
            'fecha_display': _fecha_display(c.fecha),
            'profesor':      c.profesor.nombre_corto if c.profesor else '—',
            'unidad':        unidad_str,
        })

    # Sort detail by (fecha, numero) so U1 always precedes U2 regardless of insertion order.
    for key in detalle:
        detalle[key].sort(key=lambda x: (x['fecha'], int(x['unidad']) if x['unidad'].isdigit() else 0))

    # 3. Clases adicionales (socialización S o material asignado) — sin cambio respecto al original
    detalle_adicional = defaultdict(list)  # (grado, materia) -> lista de dicts

    adicionales = (
        Clase.objects
        .filter(
            colegio=sel_col,
            cancelada=False,
            es_evento=False,
            materia__isnull=False,
        )
        .filter(
            Q(unidad='S') | Q(libro_especial__isnull=False)
        )
        .select_related('bloque__grado', 'materia', 'profesor')
        .order_by('fecha')
    )
    for c in adicionales:
        grado_nombre   = c.bloque.grado.nombre
        materia_nombre = c.materia.nombre
        colores[materia_nombre] = c.materia.color
        label = 'S' if c.unidad == 'S' else 'A'
        detalle_adicional[(grado_nombre, materia_nombre)].append({
            'fecha':         c.fecha.isoformat(),
            'fecha_display': _fecha_display(c.fecha),
            'profesor':      c.profesor.nombre_corto if c.profesor else '—',
            'unidad':        label,
            'tipo':          'adicional',
        })

    # 4. Pre-indexar para O(1) en el loop de ensamblado
    _mat_por_grado = defaultdict(set)      # grado -> set(materia)
    _lib_por_gm    = defaultdict(set)      # (grado, materia) -> set(libro_id)
    _conteo_por_gml = defaultdict(dict)    # (grado, materia, libro_id) -> {unidad_str: cnt}

    for (g, m, l) in universo:
        _mat_por_grado[g].add(m)
        if l is not None:
            _lib_por_gm[(g, m)].add(l)
    for (g, m, l, u), cnt in conteo.items():
        _mat_por_grado[g].add(m)
        if l is not None:
            _lib_por_gm[(g, m)].add(l)
        _conteo_por_gml[(g, m, l)][u] = cnt

    _adicional_excl_por_grado = defaultdict(set)  # grado -> materias SOLO en adicional
    for (g, m) in detalle_adicional:
        if m not in _mat_por_grado[g]:
            _adicional_excl_por_grado[g].add(m)

    todas_claves_grado = set(_mat_por_grado.keys()) | {g for (g, m) in detalle_adicional}
    grados_ordenados = ordenar_grados(todas_claves_grado)

    resultado = {}
    for grado in grados_ordenados:
        materias_grado = {}
        materias_set           = _mat_por_grado[grado]
        materias_solo_adicional = _adicional_excl_por_grado[grado]

        for materia in sorted(materias_set):
            libro_ids_materia = _lib_por_gm[(grado, materia)]

            libros_list = []
            for lid in sorted(libro_ids_materia, key=lambda x: libros_nombre.get(x, '')):
                unidades_libro  = universo.get((grado, materia, lid), set())
                unidades_usadas = _conteo_por_gml.get((grado, materia, lid), {})

                unidades_list = []
                for num_str in sorted(unidades_libro, key=lambda x: int(x) if x.isdigit() else 9999):
                    cnt = unidades_usadas.get(num_str, 0)
                    if cnt == 0:
                        tipo = 'pendiente'
                    elif cnt == 1:
                        tipo = 'dado'
                    else:
                        tipo = 'repetido'
                    unidades_list.append({'numero': num_str, 'count': cnt, 'tipo': tipo})

                for num_str in sorted(unidades_usadas.keys()):
                    if num_str not in unidades_libro:
                        unidades_list.append({
                            'numero': num_str,
                            'count':  unidades_usadas[num_str],
                            'tipo':   'invalido',
                        })

                libros_list.append({
                    'libro_id':    lid,
                    'libro_nombre': libros_nombre.get(lid, ''),
                    'unidades':    unidades_list,
                    'detalle':     detalle.get((grado, materia, lid), []),
                })

            # Clases cuya fecha no tiene asignación vigente (lid=None)
            unidades_sin_libro = _conteo_por_gml.get((grado, materia, None), {})
            if unidades_sin_libro:
                unidades_list = [
                    {'numero': u, 'count': cnt, 'tipo': 'invalido'}
                    for u, cnt in sorted(unidades_sin_libro.items())
                ]
                libros_list.append({
                    'libro_id':    None,
                    'libro_nombre': '(sin asignación)',
                    'unidades':    unidades_list,
                    'detalle':     detalle.get((grado, materia, None), []),
                })

            materias_grado[materia] = {
                'color':             colores.get(materia, '#6c757d'),
                'libros':            libros_list,
                'detalle_adicional': detalle_adicional.get((grado, materia), []),
            }

        for materia in sorted(materias_solo_adicional):
            materias_grado[materia] = {
                'color':             colores.get(materia, '#6c757d'),
                'libros':            [],
                'detalle_adicional': detalle_adicional.get((grado, materia), []),
            }

        if materias_grado:
            resultado[grado] = materias_grado

    return resultado



# ─────────────────────────────────────────────────────────────
# VISTA PRINCIPAL — DASHBOARD
# ─────────────────────────────────────────────────────────────
@login_required
def dashboard_colegios(request):
    """
    Vista principal de programación de clases por colegio.

    Sin colegio seleccionado: muestra solo el selector de colegio/año.
    Con colegio: carga la matriz de clases, estadísticas y datos del modal.

    Los queries de profesores y stats solo se ejecutan cuando hay un colegio
    seleccionado — evita cargar datos innecesarios en la vista vacía inicial.

    Gestores de colegio (perfil_colegio) ven solo su propio colegio, ignorando
    el parámetro id_col de la URL para prevenir acceso entre colegios.

    La sincronización de auditoría se lanza en hilo daemon para no añadir
    latencia al response del dashboard.
    """
    anio_actual = date.today().year
    anios_disponibles = sorted(set(
        ColegioAnio.objects.filter(activo=True)
        .values_list('anio', flat=True)
    ))
    anio_sel = request.GET.get('anio')
    if anio_sel:
        try:
            anio_sel = int(anio_sel)
        except ValueError:
            anio_sel = anio_actual
    else:
        anio_sel = anio_actual

    colegios = ColegioAnio.objects.filter(activo=True, anio=anio_sel).select_related('colegio').order_by('colegio__nombre')
    try:
        id_col = int(request.GET.get('id_col') or 0) or None
    except (ValueError, TypeError):
        id_col = None

    # Force colegio users to see only their own school, ignoring the URL param.
    perfil_col = getattr(request, 'perfil_colegio', None)
    if perfil_col:
        ca_activo = getattr(request, 'colegio_anio_activo', None)
        if ca_activo:
            id_col = str(ca_activo.id)

    ctx = {
        'colegios':                    colegios,
        'sel_col':                     None,
        'hoy':                         date.today().isoformat(),
        'profesores':                  [],
        'anios_disponibles':           anios_disponibles,
        'anio_sel':                    anio_sel,
        # Objeto (no cadena): el template lo serializa con json_script (escapa seguro).
        'profesores_por_materia':      {},
    }

    if id_col:
        sel_col = get_object_or_404(ColegioAnio, id=id_col)
        ctx['sel_col'] = sel_col

        if request.method == 'POST' and 'guardar_clase' in request.POST:
            if request.es_personal_programacion:
                _guardar_clase(request, sel_col)
            return redirect(request.get_full_path())

        # Profesores: una sola query con prefetch de materias — solo cuando hay colegio seleccionado
        _profes_activos = list(
            Profesor.objects
            .filter(activo=True)
            .prefetch_related('materias')
            .order_by('nombre')
        )
        _prof_mat_map = defaultdict(list)
        for _p in _profes_activos:
            for _m in _p.materias.all():
                _prof_mat_map[_m.nombre].append(_p.id)
        ctx['profesores']             = _profes_activos
        # Se pasan objetos Python al contexto; el template los serializa con
        # json_script, que escapa <, >, & y </script> (evita XSS por nombres editables).
        ctx['profesores_por_materia'] = dict(_prof_mat_map)

        # Construir tabla: solo fechas que tienen clases.
        # La ventana del periodo (rango) respeta el calendario A/B del colegio.
        inicio, fin = sel_col.rango
        # Expuestos al template para acotar el datepicker del modal "Crear clase".
        ctx['periodo_inicio'] = inicio
        ctx['periodo_fin']    = fin
        bloques_raw, bloques_agrupados = _construir_bloques_agrupados(sel_col)
        ctx['bloques_agrupados'] = bloques_agrupados
        _ck_matriz = _matriz_cache_key(sel_col.id, anio_sel)
        matriz = cache.get(_ck_matriz)
        if matriz is None:
            matriz = _construir_matriz(sel_col, bloques_raw, inicio, fin)
            cache.set(_ck_matriz, matriz, _MATRIZ_CACHE_TTL)
        ctx['matriz'] = matriz

        fechas_con_clases = sorted({
            fecha_str
            for bloque_dict in matriz.values()
            for fecha_str in bloque_dict.keys()
        })
        ctx['dias_header'] = [date.fromisoformat(f) for f in fechas_con_clases]

        # JSON de bloques por grado para el modal "Crear clase"
        bloques_json = {}
        for grado_nombre, lista_b in bloques_agrupados.items():
            bloques_json[grado_nombre] = [
                {'id': b.id, 'hora': b.hora} for b in lista_b
            ]
        ctx['bloques_data'] = bloques_json

        _ck_stats = _stats_cache_key(sel_col.id, anio_sel)
        stats = cache.get(_ck_stats)
        if stats is None:
            stats = _construir_stats(sel_col)
            cache.set(_ck_stats, stats, _STATS_CACHE_TTL)
        # json_script usa DjangoJSONEncoder (fechas ya van como isoformat en stats).
        ctx['stats_data']  = stats
        ctx['stats_vacio'] = not bool(stats)

        # Libros disponibles para material especial (solo los marcados como Material Asignado)
        libros_especiales = list(
            NombreLibro.objects.filter(activo=True, es_material_asignado=True)
            .order_by('nombre')
            .values('id', 'nombre')
        )
        ctx['libros_especiales_data'] = libros_especiales

    ctx['usuario_bloqueado'] = bool(perfil_col)

    # Alertas de auditoría vigentes para el colegio seleccionado
    if request.es_personal_programacion and ctx.get('sel_col'):
        from programacion.auditoria.models import AlertaAuditoria
        from programacion.auditoria.engine import sincronizar

        def _sync_safe():
            from django.db import connection
            try:
                sincronizar()
            except Exception:
                logger.exception('Error en sincronizar auditoria (hilo bg dashboard)')
            finally:
                # El hilo abre su propia conexión thread-local y no recibe la señal
                # request_finished, así que la cerramos a mano para evitar fugas.
                connection.close()

        # Lanzar sincronización en hilo separado para no bloquear la respuesta
        if not getattr(settings, 'TESTING', False):
            threading.Thread(target=_sync_safe, daemon=True).start()
        sel = ctx['sel_col']
        ctx['alertas_colegio'] = AlertaAuditoria.objects.filter(
            vigente=True,
        ).filter(
            Q(colegio=sel) | Q(colegios_implicados=sel)
        ).distinct().select_related('colegio__colegio', 'profesor')

    return render(request, 'colegios/dashboard.html', ctx)


# ─────────────────────────────────────────────────────────────
# REFRESH PARCIAL — STATS / TABLA (HTMX, sin recarga)
# ─────────────────────────────────────────────────────────────
@login_required
def ajax_panel_stats(request, colegio_id):
    """Retorna JSON con stats actualizados para refrescar panel sin recargar."""
    sel_col = get_object_or_404(ColegioAnio, id=colegio_id)
    cache.delete(_stats_cache_key(sel_col.id, sel_col.anio))
    stats = _construir_stats(sel_col)
    cache.set(_stats_cache_key(sel_col.id, sel_col.anio), stats, _STATS_CACHE_TTL)
    return JsonResponse({
        'stats':       stats,
        'stats_vacio': not bool(stats),
    })


@login_required
def ajax_panel_tabla(request, colegio_id):
    """Re-renderiza el partial de la tabla del dashboard (incluye fechas/celdas actualizadas)."""
    sel_col = get_object_or_404(ColegioAnio, id=colegio_id)
    cache.delete(_matriz_cache_key(sel_col.id, sel_col.anio))

    inicio, fin = sel_col.rango
    bloques_raw, bloques_agrupados = _construir_bloques_agrupados(sel_col)
    matriz = _construir_matriz(sel_col, bloques_raw, inicio, fin)
    cache.set(_matriz_cache_key(sel_col.id, sel_col.anio), matriz, _MATRIZ_CACHE_TTL)

    fechas_con_clases = sorted({
        fecha_str
        for bloque_dict in matriz.values()
        for fecha_str in bloque_dict.keys()
    })
    dias_header = [date.fromisoformat(f) for f in fechas_con_clases]

    return render(request, 'colegios/_partials/_panel_tabla.html', {
        'sel_col':           sel_col,
        'bloques_agrupados': bloques_agrupados,
        'matriz':            matriz,
        'dias_header':       dias_header,
    })


# ─────────────────────────────────────────────────────────────
# CONFIGURACIÓN DE COLEGIO — Panel integrado
# ─────────────────────────────────────────────────────────────
@login_required
@xframe_options_sameorigin
def configurar_colegio(request, colegio_id):
    """
    Panel integrado de configuración de bloques y asignaciones de un ColegioAnio.

    Se carga en un iframe dentro de la vista de configuración de colegios
    (@xframe_options_sameorigin permite el embedding desde el mismo origen).

    Maneja 6 acciones POST: add/edit/del_bloque y add/edit/del_asignacion.
    Los libros marcados como es_material_asignado=True se excluyen del selector
    de asignaciones — esos libros solo aparecen en el modal de clase como material especial.
    """
    colegio = get_object_or_404(ColegioAnio, id=colegio_id)

    # Personal de programación (superusuario / staff de área) o el usuario del colegio correspondiente
    if not request.es_personal_programacion:
        perfil = getattr(request, 'perfil_colegio', None)
        if not perfil or perfil.colegio_id != colegio.colegio_id:
            ca = getattr(request, 'colegio_anio_activo', None)
            destino = f'/colegios/?id_col={ca.id}' if ca else '/usuarios/login/'
            return redirect(destino)

    if request.method == 'POST':
        accion = request.POST.get('accion')

        if accion == 'add_bloque':
            grado_nombre = request.POST.get('grado', '').strip()
            if grado_nombre:
                grado_obj, _ = Grado.objects.get_or_create(nombre=grado_nombre)
                try:
                    hi_str = request.POST.get('hora_inicio', '')
                    hf_str = request.POST.get('hora_fin', '')
                    hora_inicio = datetime.strptime(hi_str, '%H:%M').time() if hi_str else None
                    hora_fin    = datetime.strptime(hf_str, '%H:%M').time() if hf_str else None
                except ValueError:
                    return redirect('configurar_colegio', colegio_id=colegio.id)
                bloque = Bloque.objects.create(
                    colegio     = colegio,
                    grado       = grado_obj,
                    hora_inicio = hora_inicio,
                    hora_fin    = hora_fin,
                )
                bloque.refresh_from_db()
                registrar_cambio(request, 'crear', bloque, colegio=colegio)
                # Si se proporcionó libro, crear asignación simultáneamente
                libro_nombre = request.POST.get('libro_titulo', '').strip()
                if libro_nombre:
                    libro_obj = NombreLibro.objects.filter(nombre=libro_nombre).first()
                    if libro_obj:
                        Asignacion.objects.create(
                            colegio      = colegio,
                            grado        = grado_obj,
                            libro        = libro_obj,
                            fecha_inicio = request.POST.get('fecha_inicio') or None,
                            fecha_fin    = request.POST.get('fecha_fin') or None,
                        )

        elif accion == 'edit_bloque':
            b = get_object_or_404(Bloque, id=request.POST.get('bloque_id'), colegio=colegio)
            grado_nombre = request.POST.get('grado', '').strip()
            if grado_nombre:
                grado_obj, _ = Grado.objects.get_or_create(nombre=grado_nombre)
                b.grado       = grado_obj
                try:
                    hi_str = request.POST.get('hora_inicio', '')
                    hf_str = request.POST.get('hora_fin', '')
                    b.hora_inicio = datetime.strptime(hi_str, '%H:%M').time() if hi_str else b.hora_inicio
                    b.hora_fin    = datetime.strptime(hf_str, '%H:%M').time() if hf_str else b.hora_fin
                except ValueError:
                    return redirect('configurar_colegio', colegio_id=colegio.id)
                b.save()
                registrar_cambio(request, 'editar', b, colegio=colegio)

        elif accion == 'del_bloque':
            b = get_object_or_404(Bloque, id=request.POST.get('bloque_id'), colegio=colegio)
            registrar_cambio(request, 'eliminar', b, colegio=colegio)
            b.delete()

        elif accion == 'add_asignacion':
            grado_nombre = request.POST.get('grado', '').strip()
            try:
                fecha_inicio_raw = datetime.strptime(request.POST.get('fecha_inicio', ''), '%Y-%m-%d').date() if request.POST.get('fecha_inicio') else None
                fecha_fin_raw    = datetime.strptime(request.POST.get('fecha_fin', ''), '%Y-%m-%d').date() if request.POST.get('fecha_fin') else None
            except ValueError:
                return redirect('configurar_colegio', colegio_id=colegio.id)
            if fecha_inicio_raw and fecha_fin_raw and fecha_inicio_raw >= fecha_fin_raw:
                return redirect('configurar_colegio', colegio_id=colegio.id)
            libro_nombre = request.POST.get('libro_titulo', '').strip()
            libro_obj = NombreLibro.objects.filter(nombre=libro_nombre).first() if libro_nombre else None
            if grado_nombre:
                grado_obj, _ = Grado.objects.get_or_create(nombre=grado_nombre)
                asignacion = Asignacion.objects.create(
                    colegio      = colegio,
                    grado        = grado_obj,
                    libro        = libro_obj,
                    fecha_inicio = fecha_inicio_raw,
                    fecha_fin    = fecha_fin_raw,
                )
                registrar_cambio(request, 'crear', asignacion, colegio=colegio)

        elif accion == 'edit_asignacion':
            a = get_object_or_404(Asignacion, id=request.POST.get('asignacion_id'),
                                  colegio=colegio)
            grado_nombre = request.POST.get('grado', '').strip()
            try:
                fecha_inicio_raw = datetime.strptime(request.POST.get('fecha_inicio', ''), '%Y-%m-%d').date() if request.POST.get('fecha_inicio') else None
                fecha_fin_raw    = datetime.strptime(request.POST.get('fecha_fin', ''), '%Y-%m-%d').date() if request.POST.get('fecha_fin') else None
            except ValueError:
                return redirect('configurar_colegio', colegio_id=colegio.id)
            if fecha_inicio_raw and fecha_fin_raw and fecha_inicio_raw >= fecha_fin_raw:
                return redirect('configurar_colegio', colegio_id=colegio.id)
            libro_nombre = request.POST.get('libro_titulo', '').strip()
            libro_obj = NombreLibro.objects.filter(nombre=libro_nombre).first() if libro_nombre else None
            if grado_nombre:
                grado_obj, _   = Grado.objects.get_or_create(nombre=grado_nombre)
                a.grado        = grado_obj
                a.libro        = libro_obj
                a.fecha_inicio = fecha_inicio_raw
                a.fecha_fin    = fecha_fin_raw
                a.save()
                registrar_cambio(request, 'editar', a, colegio=colegio)

        elif accion == 'del_asignacion':
            a = get_object_or_404(Asignacion, id=request.POST.get('asignacion_id'), colegio=colegio)
            registrar_cambio(request, 'eliminar', a, colegio=colegio)
            a.delete()

        elif accion == 'set_valor_hora':
            raw = request.POST.get('valor_hora', '').strip()
            try:
                valor = int(raw) if raw else None
                if valor is not None and valor < 0:
                    valor = None
            except (ValueError, TypeError):
                valor = None
            colegio.valor_hora = valor
            colegio.save(update_fields=['valor_hora'])

        return redirect('configurar_colegio', colegio_id=colegio.id)

    # GET ────────────────────────────────────────────────────
    bloques      = (Bloque.objects.filter(colegio=colegio)
                    .select_related('grado').order_by('grado__nombre', 'hora_inicio'))
    asignaciones = (Asignacion.objects.filter(colegio=colegio)
                    .select_related('grado').order_by('grado__nombre', 'fecha_inicio'))
    libros       = NombreLibro.objects.filter(activo=True, es_material_asignado=False).values_list('nombre', flat=True)
    todos_grados = Grado.objects.all()

    # Agrupar asignaciones por grado para mostrarlas junto al bloque
    asig_por_grado = defaultdict(list)
    for a in asignaciones:
        asig_por_grado[a.grado.nombre].append(a)

    return render(request, 'colegios/configurar_colegio.html', {
        'colegio':        colegio,
        'bloques':        bloques,
        'asignaciones':   asignaciones,
        'asig_por_grado': dict(asig_por_grado),
        'libros':         libros,
        'todos_grados':   todos_grados,
    })


# ─────────────────────────────────────────────────────────────
# CLONAR CONFIGURACIÓN DE COLEGIO
# ─────────────────────────────────────────────────────────────
def _shift_year(d, new_year):
    """Traslada una fecha al nuevo año, recortando el día si feb-29 no existe."""
    max_day = _calendar.monthrange(new_year, d.month)[1]
    return d.replace(year=new_year, day=min(d.day, max_day))


@login_required
@require_POST
def ajax_clonar_colegio(request, colegio_id):
    """
    Crea un ColegioAnio para el año siguiente del mismo colegio,
    duplicando sus Bloques y Asignaciones con fechas actualizadas.
    Solo accesible por personal de programación (superusuario / staff de área).
    """
    if not request.es_personal_programacion:
        return JsonResponse({'ok': False, 'error': 'Sin permisos'}, status=403)

    origen = get_object_or_404(ColegioAnio, id=colegio_id)
    nuevo_anio = origen.anio + 1

    # Verificar que no exista ya ese año para este colegio
    if ColegioAnio.objects.filter(colegio=origen.colegio, anio=nuevo_anio).exists():
        return JsonResponse({
            'ok': False,
            'error': f'Ya existe "{origen.nombre}" para el año {nuevo_anio}.'
        })

    try:
        with transaction.atomic():
            # Crear solo el ColegioAnio (el Colegio permanente ya existe)
            nuevo = ColegioAnio.objects.create(
                colegio = origen.colegio,
                anio    = nuevo_anio,
                activo  = True,
            )

            # Copiar bloques
            for b in Bloque.objects.filter(colegio=origen).select_related('grado'):
                Bloque.objects.create(
                    colegio     = nuevo,
                    grado       = b.grado,
                    hora_inicio = b.hora_inicio,
                    hora_fin    = b.hora_fin,
                )

            # Copiar asignaciones con fechas del nuevo periodo.
            # Los defaults usan la ventana real (nuevo.rango), que respeta el
            # calendario A/B. Las fechas explícitas se desplazan por años RELATIVOS
            # (delta), no al año ancla: así un periodo B que cruza dos años calendario
            # (fin en jun del año+1) conserva su cruce en vez de colapsar al ancla.
            delta = nuevo_anio - origen.anio
            rango_inicio, rango_fin = nuevo.rango
            for a in Asignacion.objects.filter(colegio=origen).select_related('grado', 'libro'):
                fi = _shift_year(a.fecha_inicio, a.fecha_inicio.year + delta) if a.fecha_inicio else rango_inicio
                ff = _shift_year(a.fecha_fin, a.fecha_fin.year + delta) if a.fecha_fin else rango_fin
                Asignacion.objects.create(
                    colegio      = nuevo,
                    grado        = a.grado,
                    libro        = a.libro,
                    fecha_inicio = fi,
                    fecha_fin    = ff,
                )

    except IntegrityError:
        return JsonResponse({
            'ok': False,
            'error': f'Ya existe "{origen.nombre}" para el año {nuevo_anio}.'
        })

    logger.info('Colegio clonado: %s %s > %s (por %s)',
                origen.nombre, origen.anio, nuevo_anio, request.user.username)
    return JsonResponse({'ok': True, 'nuevo_id': nuevo.id, 'anio': nuevo_anio})


# ─────────────────────────────────────────────────────────────
# HISTORIAL DE CAMBIOS POR COLEGIO
# ─────────────────────────────────────────────────────────────
@login_required
def historial_colegio(request, colegio_id):
    """
    Historial de cambios (crear/editar/eliminar) de un colegio específico.

    Limitado a 500 registros recientes para evitar páginas lentas; el historial
    completo está disponible en historial_global con paginación server-side.
    """
    colegio = get_object_or_404(ColegioAnio, id=colegio_id)
    if not request.es_personal_programacion:
        perfil = getattr(request, 'perfil_colegio', None)
        if not perfil or perfil.colegio_id != colegio.colegio_id:
            return redirect(f'{reverse("dashboard")}?id_col={colegio.id}')

    qs = HistorialCambio.objects.filter(colegio=colegio).select_related('usuario')
    qs, filtros = aplicar_filtros_historial(qs, request.GET)
    cambios = qs.order_by('-fecha')[:500]
    return render(request, 'colegios/historial.html', {
        'colegio': colegio,
        'cambios': cambios,
        **filtros,
    })

