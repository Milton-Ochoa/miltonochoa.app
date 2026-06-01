from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from datetime import time, date
from colegios.models import Clase, Asignacion, ClaseParticular, Grado
from configuracion.models import Colegio, Profesor, NombreLibro, Unidad, Materia
from collections import defaultdict


def extraer_minutos(hora_str):
    """
    Convierte una cadena de hora (HH:MM o rango HH:MM-HH:MM) a minutos desde medianoche.
    Se usa como clave de orden cuando `bloque.hora_inicio` es None y solo hay el string legado.
    Retorna 0 ante cualquier formato inválido para no romper el sort.
    """
    try:
        partes = str(hora_str).split('-')[0].strip().split(':')
        return int(partes[0]) * 60 + int(partes[1])
    except (ValueError, IndexError, AttributeError):
        return 0


def _libro_para_fecha(asig_map, colegio_id, grado_nombre, fecha):
    """Resuelve el título del libro asignado al grado en una fecha, usando el mapa pre-cargado.
    El mapa evita N+1: se carga una vez con todas las asignaciones de los colegios del profesor.
    """
    for a in asig_map.get((colegio_id, grado_nombre), []):
        if a.fecha_inicio and a.fecha_fin and a.fecha_inicio <= fecha <= a.fecha_fin:
            return a.libro.nombre if a.libro else 'Sin Libro'
    return 'Sin Libro'


def _resolver_unidad(unidad, unidad_obj):
    """
    Retorna (material_override, unidad_full, unidad_link) para mostrar en el horario.
    Si hay objeto Unidad, construye el texto "Nº. Nombre" y usa su link directo.
    Si no hay objeto (unidad no numérica o sin libro), retorna el valor crudo con '#'.
    `material_override` siempre es None — existe por simetría con versiones anteriores.
    """
    unidad_str = str(unidad) if unidad else ''

    if unidad_obj:
        return None, f"{unidad}. {unidad_obj.nombre}", unidad_obj.link or '#'
    return None, str(unidad_str), '#'


def _construir_entrada_clase(c, libro_titulo, unidades_map):
    """
    Construye el dict de visualización de una clase de colegio para el template del horario.
    Maneja tres variantes mutuamente excluyentes (en orden de prioridad):
      1. Socialización ('S') — sin lookup de unidad, link personal si existe
      2. Material Asignado (libro_especial != null) — usa el libro especial como fuente de unidades
      3. Normal — usa el libro asignado al grado (libro_titulo) como fuente
    `unidades_map` es pre-cargado en batch por `ver_horario`; acceso O(1) por (libro, materia, num).
    """
    unidad_str = str(c.unidad) if c.unidad else ''
    mat_nombre = c.materia.nombre if c.materia_id else ''

    if unidad_str == 'S':
        return {
            'clase':         c,
            'minutos':       c.bloque.hora_inicio.hour * 60 + c.bloque.hora_inicio.minute
                             if c.bloque.hora_inicio else extraer_minutos(c.bloque.hora),
            'material':      'Socialización de simulacro',
            'unidad_full':   'Socialización de simulacro',
            'unidad_link':   c.enlace_personalizado or '#',
            'maps_link':     getattr(c.colegio, 'mapa_link', '#') or '#',
            'es_particular': False,
        }

    if c.libro_especial_id:
        libro_real = c.libro_especial.nombre
        unidad_obj = unidades_map.get((libro_real, mat_nombre, unidad_str)) if unidad_str.isdigit() else None
        _, unidad_full, unidad_link = _resolver_unidad(c.unidad, unidad_obj)
        if not unidad_link or unidad_link == '#':
            unidad_link = c.enlace_personalizado or '#'
        return {
            'clase':         c,
            'minutos':       c.bloque.hora_inicio.hour * 60 + c.bloque.hora_inicio.minute
                             if c.bloque.hora_inicio else extraer_minutos(c.bloque.hora),
            'material':      libro_real,
            'unidad_full':   unidad_full,
            'unidad_link':   unidad_link,
            'maps_link':     getattr(c.colegio, 'mapa_link', '#') or '#',
            'es_particular': False,
        }

    unidad_obj = unidades_map.get((libro_titulo, mat_nombre, unidad_str)) if unidad_str.isdigit() else None
    material_override, unidad_full, unidad_link = _resolver_unidad(c.unidad, unidad_obj)

    return {
        'clase':         c,
        'minutos':       c.bloque.hora_inicio.hour * 60 + c.bloque.hora_inicio.minute
                         if c.bloque.hora_inicio else extraer_minutos(c.bloque.hora),
        'material':      material_override if material_override else libro_titulo,
        'unidad_full':   unidad_full,
        'unidad_link':   unidad_link,
        'maps_link':     getattr(c.colegio, 'mapa_link', '#') or '#',
        'es_particular': False,
    }


def _construir_entrada_particular(p, unidades_map):
    """
    Construye el dict de visualización de una ClaseParticular para el template del horario.
    Incluye `raw_data` con todos los campos editables para pre-poblar el modal de edición.
    `ciudad` es texto libre — puede contener dirección completa, no solo ciudad.
    """
    minutos = (p.hora_inicio.hour * 60 + p.hora_inicio.minute) if p.hora_inicio else 0
    mat_nombre = p.materia.nombre if p.materia_id else ''

    if p.material == 'S':
        return {
            'particular_obj': p,
            'minutos':        minutos,
            'material':       'Socialización de simulacro',
            'unidad_full':    'Socialización de simulacro',
            'unidad_link':    '#',
            'maps_link':      p.mapa_link or '#',
            'es_particular':  True,
            'particular_id':  p.id,
            'raw_data': {
                'estudiante':   p.estudiante,
                'ciudad':       p.ciudad,
                'mapa_link':    p.mapa_link or '',
                'fecha':        p.fecha.strftime('%Y-%m-%d'),
                'hora_inicio':  p.hora_inicio.strftime('%H:%M') if p.hora_inicio else '08:00',
                'hora_fin':     p.hora_fin.strftime('%H:%M') if p.hora_fin else '10:00',
                'grado':        p.grado.nombre,
                'materia':      mat_nombre,
                'unidad':       p.unidad,
                'material':     p.material,
            },
        }

    unidad_str = str(p.unidad) if p.unidad else ''
    unidad_obj = unidades_map.get((p.material, mat_nombre, unidad_str)) if unidad_str.isdigit() else None

    material_override, unidad_full, unidad_link = _resolver_unidad(p.unidad, unidad_obj)

    return {
        'particular_obj': p,
        'minutos':        minutos,
        'material':       material_override if material_override else p.material,
        'unidad_full':    unidad_full,
        'unidad_link':    unidad_link,
        'maps_link':      p.mapa_link or '#',
        'es_particular':  True,
        'particular_id':  p.id,
        'raw_data': {
            'estudiante':   p.estudiante,
            'ciudad':       p.ciudad,
            'mapa_link':    p.mapa_link or '',
            'fecha':        p.fecha.strftime('%Y-%m-%d'),
            'hora_inicio':  p.hora_inicio.strftime('%H:%M') if p.hora_inicio else '08:00',
            'hora_fin':     p.hora_fin.strftime('%H:%M') if p.hora_fin else '10:00',
            'grado':        p.grado.nombre,
            'materia':      mat_nombre,
            'unidad':       p.unidad,
            'material':     p.material,
        },
    }


@login_required
def obtener_asignaturas_particular(request):
    """
    Retorna las materias disponibles según el tipo de material de una clase particular.
    'A' o 'S' (Material Asignado/Socialización) → todas las materias del sistema.
    Nombre de libro → solo las materias que tienen unidades en ese libro.
    """
    material = request.GET.get('material')
    if not material:
        return JsonResponse([], safe=False)
    if material in ('A', 'S'):
        asignaturas = list(Materia.objects.values_list('nombre', flat=True).order_by('nombre'))
    else:
        asignaturas = sorted(set(
            Unidad.objects.filter(libro__nombre=material)
            .values_list('materia__nombre', flat=True)
        ))
    return JsonResponse(asignaturas, safe=False)


@login_required
def obtener_unidades_particular(request):
    """Retorna las unidades de un libro filtradas por materia, para el selector del modal de clase particular."""
    material = request.GET.get('material')
    materia  = request.GET.get('materia')
    if not (material and materia):
        return JsonResponse([], safe=False)
    unidades = list(
        Unidad.objects.filter(libro__nombre=material, materia__nombre=materia)
        .order_by('numero')
        .values('numero', 'nombre')
    )
    return JsonResponse(
        [{'unidad': u['numero'], 'nombre_unidad': u['nombre']} for u in unidades],
        safe=False
    )


@login_required
def ver_horario(request):
    """
    Horario personal del profesor: clases de colegios + clases particulares, agrupadas por fecha.

    Tres roles posibles:
      - Superusuario/staff: ve a cualquier profesor (selector visible, puede gestionar particulares)
      - Profesor (perfil_profesor): forzado a su propio horario (selector oculto, `usuario_bloqueado=True`)
      - POST (guardar/editar/eliminar particulares): solo para staff; scoped siempre por `profesor_id`
        en el .filter() de ClaseParticular para prevenir ediciones cruzadas entre profesores.

    Optimización N+1:
      - asig_map: una query de Asignacion para todos los colegios del profesor (no una por clase)
      - unidades_map: una query de Unidad cubriendo todos los libros de clases y particulares
      - Acceso O(1) con clave (libro, materia, numero_str)
    """
    if request.method == 'POST' and request.user.is_staff:
        profesor_id = request.POST.get('profesor_id')

        if 'guardar_particular' in request.POST:
            grado_obj, _ = Grado.objects.get_or_create(nombre=request.POST.get('grado', '').strip())
            materia_obj, _ = Materia.objects.get_or_create(nombre=request.POST.get('materia', '').strip())
            ClaseParticular.objects.create(
                profesor_id = profesor_id,
                estudiante  = request.POST.get('estudiante'),
                ciudad      = request.POST.get('ciudad'),
                mapa_link   = request.POST.get('mapa_link'),
                fecha       = request.POST.get('fecha'),
                hora_inicio = request.POST.get('hora_inicio'),
                hora_fin    = request.POST.get('hora_fin'),
                grado       = grado_obj,
                material    = request.POST.get('material'),
                materia     = materia_obj,
                unidad      = request.POST.get('unidad'),
            )
        elif 'editar_particular' in request.POST:
            grado_obj, _ = Grado.objects.get_or_create(nombre=request.POST.get('grado', '').strip())
            materia_obj, _ = Materia.objects.get_or_create(nombre=request.POST.get('materia', '').strip())
            # Scoped to the correct professor to prevent cross-professor edits
            ClaseParticular.objects.filter(
                id=request.POST.get('particular_id'),
                profesor_id=profesor_id,
            ).update(
                estudiante  = request.POST.get('estudiante'),
                ciudad      = request.POST.get('ciudad'),
                mapa_link   = request.POST.get('mapa_link'),
                fecha       = request.POST.get('fecha'),
                hora_inicio = request.POST.get('hora_inicio'),
                hora_fin    = request.POST.get('hora_fin'),
                grado       = grado_obj,
                material    = request.POST.get('material'),
                materia     = materia_obj,
                unidad      = request.POST.get('unidad'),
            )
        elif 'eliminar_particular' in request.POST:
            # Scoped to the correct professor to prevent cross-professor deletes
            ClaseParticular.objects.filter(
                id=request.POST.get('particular_id'),
                profesor_id=profesor_id,
            ).delete()

        return redirect(f"{request.path}?profesor_id={profesor_id}")

    perfil_prof = getattr(request, 'perfil_profesor', None)
    if perfil_prof:
        profesor_id = str(perfil_prof.profesor_id)
    else:
        profesor_id = request.GET.get('profesor_id')

    profesores   = Profesor.objects.filter(activo=True).only('id', 'nombre', 'apellido').order_by('nombre')
    todos_libros = NombreLibro.objects.filter(activo=True).values_list('nombre', flat=True).order_by('nombre')
    agrupado_por_fecha = []

    if profesor_id:
        temp_dict = defaultdict(list)

        clases = list(
            Clase.objects
            .filter(profesor_id=profesor_id, cancelada=False, es_evento=False)
            .select_related('colegio__colegio', 'bloque__grado', 'materia', 'libro_especial')
            .only(
                'fecha', 'materia', 'unidad', 'es_evento', 'titulo_evento',
                'cancelada', 'colegio_id', 'enlace_personalizado',
                'colegio__colegio__nombre', 'colegio__colegio__ciudad', 'colegio__colegio__mapa_link',
                'colegio__anio',
                'bloque__hora_inicio', 'bloque__hora_fin',
                'bloque__grado__nombre',
                'materia__nombre',
                'libro_especial__nombre',
            )
            .order_by('fecha')
        )

        # Pre-load assignments for all relevant schools in one query
        colegios_ids = {c.colegio_id for c in clases}
        asig_map = defaultdict(list)
        if colegios_ids:
            for a in Asignacion.objects.filter(
                colegio_id__in=colegios_ids
            ).select_related('grado', 'libro').only(
                'colegio_id', 'libro__nombre', 'fecha_inicio', 'fecha_fin',
                'grado__nombre'
            ):
                asig_map[(a.colegio_id, a.grado.nombre)].append(a)

        particulares = list(
            ClaseParticular.objects
            .filter(profesor_id=profesor_id)
            .select_related('materia', 'grado')
            .order_by('fecha')
        )

        # Single batch query covering all books from both classes and particulars
        titulos_clases = set()
        for c in clases:
            if c.libro_especial_id:
                titulos_clases.add(c.libro_especial.nombre)
            else:
                t = _libro_para_fecha(asig_map, c.colegio_id, c.bloque.grado.nombre, c.fecha)
                if t and t != 'Sin Libro':
                    titulos_clases.add(t)
        titulos_part = {p.material for p in particulares
                        if p.material and p.material not in ('A', 'S')}

        todos_titulos = titulos_clases | titulos_part

        unidades_map = {}
        if todos_titulos:
            for u in Unidad.objects.filter(
                libro__nombre__in=todos_titulos
            ).select_related('libro', 'materia').only(
                'numero', 'nombre', 'link',
                'libro__nombre', 'materia__nombre'
            ):
                unidades_map[(u.libro.nombre, u.materia.nombre, str(u.numero))] = u

        for c in clases:
            grado_nombre = c.bloque.grado.nombre
            libro_titulo = _libro_para_fecha(asig_map, c.colegio_id, grado_nombre, c.fecha)
            temp_dict[c.fecha].append(_construir_entrada_clase(c, libro_titulo, unidades_map))

        for p in particulares:
            temp_dict[p.fecha].append(_construir_entrada_particular(p, unidades_map))

        for fecha in sorted(temp_dict.keys()):
            clases_del_dia = sorted(temp_dict[fecha], key=lambda x: x['minutos'])
            agrupado_por_fecha.append({
                'fecha':    fecha,
                'cantidad': len(clases_del_dia),
                'clases':   clases_del_dia,
            })

    todos_grados = Grado.objects.values_list('nombre', flat=True).order_by('nombre')

    return render(request, 'profesores/horario.html', {
        'profesores':       profesores,
        'agrupado':         agrupado_por_fecha,
        'profesor_sel':     profesor_id,
        'todos_libros':     todos_libros,
        'todos_grados':     todos_grados,
        'usuario_bloqueado': bool(perfil_prof),
        'hoy':              date.today().isoformat(),
    })

