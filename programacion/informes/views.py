from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta
from .models import Informe
from programacion.configuracion.models import Profesor
from programacion.colegios.models import Clase, Asignacion
from programacion.colegios.historial import registrar_cambio
import json
import logging
import re

logger = logging.getLogger('aamo')

# Regex para extraer solo el número de unidad (descarta títulos largos del campo `tematica`).
_RE_NUMERO = re.compile(r'\d+')

# Caché de la lista de filas. La página tarda ~3s en producción por latencia de red
# a Supabase (3 queries × ~1s). Cachear el resultado por usuario evita re-pagar ese
# costo en cada visita; se invalida al crear o borrar un informe (ver más abajo).
_CACHE_TTL_LISTA = 300  # 5 minutos


def _cache_key_lista(user):
    return f'informes_lista:user:{user.id}'


def _invalidar_cache_lista():
    """Borra todas las versiones cacheadas de la lista de informes.

    Llamado tras guardar o eliminar un informe. Como la caché es por usuario,
    usamos `delete_pattern` cuando esté disponible (Redis) y caemos a un
    fallback simple en locmem (que ignora el patrón pero el TTL corto compensa).
    """
    try:
        cache.delete_pattern('informes_lista:user:*')
    except (AttributeError, NotImplementedError):
        # locmem no soporta delete_pattern; el TTL de 5 min asegura coherencia eventual
        pass


def _solo_numero_unidad(valor):
    """Devuelve solo el número de unidad ('Unidad 3: ...' → '3').

    Si no hay dígitos, devuelve el valor original sin espacios (p. ej. 'S' para
    socializaciones). El campo `tematica` del Informe a veces guarda el título
    completo de la unidad; los gestores solo quieren ver el número.
    """
    if not valor:
        return ''
    m = _RE_NUMERO.search(valor)
    return m.group(0) if m else valor.strip()


# ── Helper: resolver perfil desde request ─────────────────────────────────────

def _resolver_perfil(request):
    """
    Extrae los perfiles de rol del request.

    El middleware inyecta los perfiles como atributos del request para evitar
    queries repetidas. Si por algún motivo no están presentes (p. ej. en tests
    sin middleware), cae al ORM como respaldo. Devuelve (None, None) para
    superusuarios, que no tienen perfil por diseño.

    Returns:
        (UsuarioProfesor | None, UsuarioColegio | None)
    """
    perfil_profesor = getattr(request, 'perfil_profesor', None)
    if perfil_profesor is None:
        try:
            perfil_profesor = request.user.perfil_profesor
        except Exception:
            perfil_profesor = None

    perfil_colegio = getattr(request, 'perfil_colegio', None)
    if perfil_colegio is None:
        try:
            perfil_colegio = request.user.perfil_colegio
        except Exception:
            perfil_colegio = None

    return perfil_profesor, perfil_colegio


# ── AJAX: obtener informe existente (o vacío) para una clase ──────────────────

@login_required
def obtener_informe(request):
    """
    Devuelve los datos de un informe existente, o {'existe': False} si no hay.

    Llamado desde el modal de informe en los cronogramas. El frontend usa
    'existe' para decidir si pre-cargar el formulario o presentarlo vacío.
    Acepta clase_id (Clase regular) o particular_id (ClaseParticular).
    """
    clase_id       = request.GET.get('clase_id')
    particular_id  = request.GET.get('particular_id')

    informe = None
    if clase_id:
        informe = Informe.objects.filter(clase_id=clase_id).first()
    elif particular_id:
        informe = Informe.objects.filter(clase_particular_id=particular_id).first()

    if informe:
        data = {
            'existe':          True,
            'informe_id':      informe.id,
            'colegio_nombre':  informe.colegio_nombre,
            'grado':           informe.grado,
            'fecha':           informe.fecha.strftime('%d/%m/%Y'),
            'materia':         informe.materia,
            'tematica':        informe.tematica,
            'material':        informe.material,
            'actividades':     informe.actividades,
            'fortalezas':      informe.fortalezas,
            'debilidades':     informe.debilidades,
            'recomendaciones': informe.recomendaciones,
            'bibliografia':    informe.bibliografia,
        }
    else:
        data = {'existe': False}

    return JsonResponse(data)


# ── AJAX: guardar informe ──────────────────────────────────────────────────────

@login_required
@require_POST
def guardar_informe(request):
    """
    Crea o actualiza un informe de sesión.

    Seguridad crítica: si el solicitante tiene perfil de profesor, se ignora
    cualquier profesor_id que venga en el body y se usa el del perfil vinculado.
    Esto impide que un profesor guarde informes bajo el nombre de otro colega
    manipulando el payload de la petición.

    Usa update_or_create con lookup por clase_id o particular_id para que
    re-guardar un informe sea idempotente (no crea duplicados).
    """
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'JSON inválido'}, status=400)

    clase_id      = body.get('clase_id')
    particular_id = body.get('particular_id')
    profesor_id   = body.get('profesor_id')

    # Blindaje de identidad: el perfil del middleware no puede falsificarse desde POST.
    perfil_profesor, _ = _resolver_perfil(request)
    if perfil_profesor:
        profesor_id = perfil_profesor.profesor_id

    if not profesor_id:
        return JsonResponse({'ok': False, 'error': 'Falta profesor_id'}, status=400)

    # Agrupar campos de texto para no repetir la extracción dos veces
    campos_texto = {
        'actividades':     body.get('actividades', '').strip(),
        'fortalezas':      body.get('fortalezas', '').strip(),
        'debilidades':     body.get('debilidades', '').strip(),
        'recomendaciones': body.get('recomendaciones', '').strip(),
        'bibliografia':    body.get('bibliografia', '').strip(),
    }

    if clase_id:
        informe, creado = Informe.objects.update_or_create(
            clase_id=clase_id,
            defaults={
                'profesor_id':    profesor_id,
                'colegio_nombre': body.get('colegio_nombre', ''),
                'grado':          body.get('grado', ''),
                'fecha':          body.get('fecha_iso'),
                'materia':        body.get('materia', ''),
                'tematica':       body.get('tematica', ''),
                'material':       body.get('material', ''),
                **campos_texto,
            }
        )
        logger.info(f'Informe guardado: id={informe.id} (por {request.user.username})')
        registrar_cambio(request, 'crear' if creado else 'editar', informe)
    elif particular_id:
        informe, creado = Informe.objects.update_or_create(
            clase_particular_id=particular_id,
            defaults={
                'profesor_id':    profesor_id,
                'colegio_nombre': body.get('colegio_nombre', ''),
                'grado':          body.get('grado', ''),
                'fecha':          body.get('fecha_iso'),
                'materia':        body.get('materia', ''),
                'tematica':       body.get('tematica', ''),
                'material':       body.get('material', ''),
                **campos_texto,
            }
        )
        logger.info(f'Informe guardado: id={informe.id} (por {request.user.username})')
        registrar_cambio(request, 'crear' if creado else 'editar', informe)
    else:
        return JsonResponse({'ok': False, 'error': 'Falta clase_id o particular_id'}, status=400)

    _invalidar_cache_lista()
    return JsonResponse({'ok': True, 'informe_id': informe.id})


# ── Vista de lista de informes ─────────────────────────────────────────────────

@login_required
def lista_informes(request):
    """
    Lista de informes + clases pendientes por documentar.

    Una fila representa o bien un Informe existente, o bien una Clase ya dictada
    sin informe asociado (estado "Pendiente"). Solo se incluyen pendientes con
    fecha <= ayer: las clases de hoy/futuro no se cuentan como pendientes porque
    aún no se han dictado.

    Visibilidad por rol:
    - Superusuario: todos los informes y clases del sistema.
    - Profesor:     solo sus propias filas (filtro por FK profesor).
    - Gestor:       todas las filas de su colegio.

    El template recibe TODO el dataset y delega filtrado/paginación a JS
    (patrón usado en configuracion/profesores.html). Se prefiere `values_list`
    sobre `select_related` para evitar el costo de instanciar miles de objetos
    ORM completos: el dataset típico ronda las 1-2k filas en un año académico.
    """
    perfil_profesor, perfil_colegio = _resolver_perfil(request)

    cache_key = _cache_key_lista(request.user)
    filas = cache.get(cache_key)
    if filas is not None:
        return render(request, 'informes/lista.html', {
            'filas':               filas,
            'es_usuario_colegio':  bool(perfil_colegio),
            'es_usuario_profesor': bool(perfil_profesor),
        })

    ayer = timezone.localdate() - timedelta(days=1)

    # ── 1. Informes existentes ────────────────────────────────────────────────
    informes_qs = Informe.objects.all()
    if perfil_profesor:
        informes_qs = informes_qs.filter(profesor=perfil_profesor.profesor)
    elif perfil_colegio:
        informes_qs = informes_qs.filter(colegio_nombre=perfil_colegio.colegio.nombre)
    # Borradores futuros se ocultan (regla "no mostrar futuro como pendiente").
    informes_qs = informes_qs.filter(Q(fecha__lte=ayer) | ~Q(actividades=''))

    informes_data = informes_qs.values_list(
        'id', 'fecha', 'colegio_nombre', 'grado', 'materia',
        'tematica', 'material', 'actividades',
        'profesor__nombre', 'profesor__apellido',
    )

    filas = []
    for (inf_id, fecha, colegio_nombre, grado, materia, tematica, material,
         actividades, prof_nombre, prof_apellido) in informes_data:
        primer_nombre   = (prof_nombre or '').split(' ', 1)[0]
        primer_apellido = (prof_apellido or '').split(' ', 1)[0]
        filas.append({
            'informe_id':     inf_id,
            'fecha':          fecha,
            'profesor':       f"{primer_nombre} {primer_apellido}".strip(),
            'colegio_nombre': colegio_nombre,
            'grado':          grado,
            'materia':        materia,
            'unidad':         _solo_numero_unidad(tematica),
            'material':       material or '',
            'completado':     bool((actividades or '').strip()),
        })

    # ── 2. Clases pendientes (sin informe, ya dictadas) ──────────────────────
    clases_qs = Clase.objects.filter(
        fecha__lte=ayer, informe__isnull=True,
        cancelada=False, es_evento=False,
    )
    if perfil_profesor:
        clases_qs = clases_qs.filter(profesor=perfil_profesor.profesor)
    elif perfil_colegio:
        clases_qs = clases_qs.filter(colegio__colegio=perfil_colegio.colegio)

    clases_data = clases_qs.values_list(
        'id', 'fecha', 'colegio__colegio__nombre', 'bloque__grado__nombre',
        'materia__nombre', 'unidad', 'libro_especial__nombre',
        'profesor__nombre', 'profesor__apellido',
        'colegio_id', 'bloque__grado_id',
    )
    # Materializo una sola vez: necesito iterar dos veces (claves de cache + filas)
    clases_data = list(clases_data)

    # Bulk-load de Asignaciones: una query única indexada por (colegio_anio, grado).
    # Para 2k clases con 30 (colegio,grado) distintos, evita 30 queries individuales.
    claves_cg = {(c[9], c[10]) for c in clases_data}
    asignaciones_idx = {}  # (colegio_id, grado_id) -> [(fecha_ini, fecha_fin, libro_nombre), ...]
    if claves_cg:
        cg_filter = Q()
        for cid, gid in claves_cg:
            cg_filter |= Q(colegio_id=cid, grado_id=gid)
        for a in Asignacion.objects.filter(cg_filter).values_list(
            'colegio_id', 'grado_id', 'fecha_inicio', 'fecha_fin', 'libro__nombre'
        ):
            asignaciones_idx.setdefault((a[0], a[1]), []).append((a[2], a[3], a[4] or ''))

    def _libro_en(colegio_id, grado_id, fecha):
        for fi, ff, libro in asignaciones_idx.get((colegio_id, grado_id), ()):
            if fi <= fecha <= ff and libro:
                return libro
        return ''

    for (cl_id, fecha, colegio_nombre, grado_nombre, materia_nombre, unidad,
         libro_especial, prof_nombre, prof_apellido, colegio_id, grado_id) in clases_data:
        primer_nombre   = (prof_nombre or '').split(' ', 1)[0]
        primer_apellido = (prof_apellido or '').split(' ', 1)[0]
        material = libro_especial or _libro_en(colegio_id, grado_id, fecha)
        filas.append({
            'informe_id':     None,
            'fecha':          fecha,
            'profesor':       f"{primer_nombre} {primer_apellido}".strip(),
            'colegio_nombre': colegio_nombre or '',
            'grado':          grado_nombre or '',
            'materia':        materia_nombre or '',
            'unidad':         _solo_numero_unidad(unidad),
            'material':       material,
            'completado':     False,
        })

    filas.sort(key=lambda r: (r['fecha'], r['colegio_nombre']), reverse=True)

    cache.set(cache_key, filas, _CACHE_TTL_LISTA)

    return render(request, 'informes/lista.html', {
        'filas':               filas,
        # Flags de UI: ocultan controles que el usuario no necesita según su rol
        'es_usuario_colegio':  bool(perfil_colegio),
        'es_usuario_profesor': bool(perfil_profesor),
    })


# ── Eliminar informe (solo superusuario) ──────────────────────────────────────

@login_required
def eliminar_informe(request, informe_id):
    """
    Elimina un informe. Restringido a superusuario para proteger el historial pedagógico.
    Registra el cambio en auditoría antes de borrar para dejar trazabilidad.
    """
    if not request.user.is_superuser:
        return JsonResponse({'ok': False, 'error': 'Sin permiso'}, status=403)
    informe = get_object_or_404(Informe, id=informe_id)
    registrar_cambio(request, 'eliminar', informe)
    informe.delete()
    _invalidar_cache_lista()
    messages.success(request, 'Informe eliminado correctamente.')
    return redirect('lista_informes')


# ── Vista detalle de un informe ───────────────────────────────────────────────

@login_required
def detalle_informe(request, informe_id):
    """
    Muestra el detalle completo de un informe.

    Un profesor solo puede ver sus propios informes. Gestores y superusuarios
    pueden ver cualquiera dentro de su ámbito (el middleware ya restringe el
    acceso a la sección /informes/).
    """
    informe = get_object_or_404(Informe, id=informe_id)

    perfil_profesor, _ = _resolver_perfil(request)
    if perfil_profesor and informe.profesor != perfil_profesor.profesor:
        return HttpResponseForbidden()

    return render(request, 'informes/detalle.html', {'informe': informe})
