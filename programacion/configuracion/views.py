from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import user_passes_test, login_required
from django.http import JsonResponse
from django.db.models import Count, Prefetch
from datetime import date
import json
import re

# La misma regex que en models.py — se duplica aquí para validar en la capa
# de vista antes de llegar al model.full_clean(), dando error AJAX inmediato.
_HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?$')

from .models import NombreLibro, Materia, Unidad, Colegio, ColegioAnio, Profesor
from .forms import ColegioForm, ProfesorForm
from .colombia_geo import DEPARTAMENTOS, DEPARTAMENTOS_CIUDADES, ciudades_de
from usuarios.ratelimit import rate_limit
from programacion.colegios.historial import registrar_cambio

# Decorador reutilizable — centraliza la verificación de superusuario para
# todas las vistas de configuración sin repetir el lambda en cada una.
solo_superusuario = user_passes_test(lambda u: u.is_superuser)


# ─────────────────────────────────────────────────────────────
# LIBROS
# ─────────────────────────────────────────────────────────────

@solo_superusuario
def configuracion_libros(request):
    """Lista todos los libros del catálogo con sus materias y conteo de unidades.

    El prefetch de unidades__materia evita N+1 al construir materias_str.
    El annotate num_unidades es más barato que len(libro.unidades.all()) en el loop.
    """
    libros = (
        NombreLibro.objects
        .annotate(num_unidades=Count('unidades', distinct=True))
        .prefetch_related(Prefetch('unidades__materia'))
        .order_by('nombre')
    )

    # Se construye un dict enriquecido en Python en lugar de pasarle el queryset
    # al template directamente, porque materias_str requiere join de set.
    libros_ctx = []
    for libro in libros:
        materias_libro = sorted({u.materia for u in libro.unidades.all()}, key=lambda m: m.nombre)
        libros_ctx.append({
            'libro':         libro,
            'materias_objs': materias_libro,
            'materias_str':  ' | '.join(m.nombre for m in materias_libro),
            'num_unidades':  libro.num_unidades,
        })

    materias = Materia.objects.all()
    return render(request, 'configuracion/libros.html', {
        'libros_ctx': libros_ctx,
        'materias':   materias,
    })


@solo_superusuario
@rate_limit(max_calls=120, periodo=60)
def ajax_crear_libro(request):
    """Crea un libro nuevo. Rechaza duplicados por nombre (case-insensitive)."""
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)
    nombre = request.POST.get('nombre', '').strip()
    if not nombre:
        return JsonResponse({'ok': False, 'error': 'El nombre es obligatorio'})
    if NombreLibro.objects.filter(nombre__iexact=nombre).exists():
        return JsonResponse({'ok': False, 'error': 'Ya existe un libro con ese nombre'})
    libro = NombreLibro.objects.create(nombre=nombre)
    return JsonResponse({'ok': True, 'id': libro.id, 'nombre': libro.nombre, 'activo': libro.activo})


@solo_superusuario
@rate_limit(max_calls=120, periodo=60)
def ajax_editar_libro(request, libro_id):
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)
    libro  = get_object_or_404(NombreLibro, id=libro_id)
    nombre = request.POST.get('nombre', '').strip()
    if not nombre:
        return JsonResponse({'ok': False, 'error': 'El nombre es obligatorio'})
    if NombreLibro.objects.filter(nombre__iexact=nombre).exclude(id=libro_id).exists():
        return JsonResponse({'ok': False, 'error': 'Ya existe un libro con ese nombre'})
    libro.nombre = nombre
    libro.save()
    return JsonResponse({'ok': True, 'nombre': libro.nombre})


@solo_superusuario
@rate_limit(max_calls=120, periodo=60)
def ajax_toggle_libro(request, libro_id):
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)
    libro = get_object_or_404(NombreLibro, id=libro_id)
    libro.activo = not libro.activo
    libro.save()
    return JsonResponse({'ok': True, 'activo': libro.activo})


@solo_superusuario
@rate_limit(max_calls=120, periodo=60)
def ajax_toggle_material_asignado(request, libro_id):
    """Alterna el flag es_material_asignado del libro.

    Cuando es True, el libro desaparece del selector de Asignaciones normales
    y solo aparece en el modal de clase como "Material Asignado". Esto evita
    que un material extra se confunda con el libro principal del grado.
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)
    libro = get_object_or_404(NombreLibro, id=libro_id)
    libro.es_material_asignado = not libro.es_material_asignado
    libro.save()
    return JsonResponse({'ok': True, 'es_material_asignado': libro.es_material_asignado})


@solo_superusuario
@rate_limit(max_calls=120, periodo=60)
def ajax_eliminar_libro(request, libro_id):
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)
    libro = get_object_or_404(NombreLibro, id=libro_id)
    libro.delete()
    return JsonResponse({'ok': True})


@solo_superusuario
@rate_limit(max_calls=120, periodo=60)
def ajax_unidades_libro(request, libro_id):
    """
    Retorna las unidades del libro, opcionalmente filtradas por materia.

    Sin materia_id retorna todas las unidades (para el panel de gestión del libro).
    Con materia_id retorna solo las unidades de esa materia (para filtros en modales).
    También devuelve metadatos del libro (nombre, activo, es_material_asignado)
    para que el frontend pueda actualizar el header del modal sin recargar la página.
    """
    libro      = get_object_or_404(NombreLibro, id=libro_id)
    materia_id = request.GET.get('materia_id')
    unidades   = Unidad.objects.filter(libro=libro).select_related('materia').order_by('materia__nombre', 'numero')
    if materia_id:
        unidades = unidades.filter(materia_id=materia_id)
    data = [{
        'id': u.id, 'materia': u.materia.nombre, 'materia_id': u.materia.id,
        'materia_color': u.materia.color,
        'numero': u.numero, 'nombre': u.nombre, 'link': u.link or '',
    } for u in unidades]
    return JsonResponse({'ok': True, 'unidades': data,
                         'libro_nombre': libro.nombre, 'libro_activo': libro.activo,
                         'libro_es_material_asignado': libro.es_material_asignado})


@solo_superusuario
@rate_limit(max_calls=120, periodo=60)
def ajax_crear_unidad(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)
    libro_id   = request.POST.get('libro_id')
    materia_id = request.POST.get('materia_id')
    numero     = request.POST.get('numero', '').strip()
    nombre     = request.POST.get('nombre', '').strip()
    link       = request.POST.get('link', '').strip() or None
    if not all([libro_id, materia_id, numero, nombre]):
        return JsonResponse({'ok': False, 'error': 'Faltan campos obligatorios'})
    try:
        numero_int = int(numero)
        if numero_int < 1:
            raise ValueError
    except ValueError:
        return JsonResponse({'ok': False, 'error': 'El número debe ser un entero positivo'})
    libro   = get_object_or_404(NombreLibro, id=libro_id)
    materia = get_object_or_404(Materia, id=materia_id)
    if Unidad.objects.filter(libro=libro, materia=materia, numero=numero_int).exists():
        return JsonResponse({'ok': False, 'error': f'Ya existe la unidad {numero} para esta materia en este libro'})
    u = Unidad.objects.create(libro=libro, materia=materia, numero=numero_int, nombre=nombre, link=link)
    return JsonResponse({'ok': True, 'id': u.id, 'materia': materia.nombre, 'materia_id': materia.id,
                         'numero': u.numero, 'nombre': u.nombre, 'link': u.link or ''})


@solo_superusuario
@rate_limit(max_calls=120, periodo=60)
def ajax_editar_unidad(request, unidad_id):
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)
    unidad     = get_object_or_404(Unidad, id=unidad_id)
    materia_id = request.POST.get('materia_id')
    numero     = request.POST.get('numero', '').strip()
    nombre     = request.POST.get('nombre', '').strip()
    link       = request.POST.get('link', '').strip() or None
    if not all([materia_id, numero, nombre]):
        return JsonResponse({'ok': False, 'error': 'Faltan campos obligatorios'})
    try:
        numero_int = int(numero)
        if numero_int < 1:
            raise ValueError
    except ValueError:
        return JsonResponse({'ok': False, 'error': 'El número debe ser un entero positivo'})
    materia = get_object_or_404(Materia, id=materia_id)
    if Unidad.objects.filter(libro=unidad.libro, materia=materia, numero=numero_int).exclude(id=unidad_id).exists():
        return JsonResponse({'ok': False, 'error': f'Ya existe la unidad {numero} para esta materia en este libro'})
    unidad.materia = materia
    unidad.numero  = numero_int
    unidad.nombre  = nombre
    unidad.link    = link
    unidad.save()
    return JsonResponse({'ok': True, 'materia': materia.nombre, 'materia_id': materia.id,
                         'numero': unidad.numero, 'nombre': unidad.nombre, 'link': unidad.link or ''})


@solo_superusuario
@rate_limit(max_calls=120, periodo=60)
def ajax_eliminar_unidad(request, unidad_id):
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)
    Unidad.objects.filter(id=unidad_id).delete()
    return JsonResponse({'ok': True})


@solo_superusuario
@rate_limit(max_calls=120, periodo=60)
def ajax_materias(request):
    return JsonResponse({'ok': True, 'materias': list(Materia.objects.values('id', 'nombre'))})


@solo_superusuario
@rate_limit(max_calls=120, periodo=60)
def ajax_crear_materia(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)
    nombre = request.POST.get('nombre', '').strip()
    if not nombre:
        return JsonResponse({'ok': False, 'error': 'El nombre es obligatorio'})
    if Materia.objects.filter(nombre__iexact=nombre).exists():
        return JsonResponse({'ok': False, 'error': 'Ya existe esa materia'})
    color = request.POST.get('color', '#6c757d').strip()
    if not _HEX_COLOR_RE.match(color):
        color = '#6c757d'
    m = Materia.objects.create(nombre=nombre, color=color)
    return JsonResponse({'ok': True, 'id': m.id, 'nombre': m.nombre, 'color': m.color})


@solo_superusuario
@rate_limit(max_calls=120, periodo=60)
def ajax_editar_materia(request, materia_id):
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)
    materia = get_object_or_404(Materia, id=materia_id)
    nombre  = request.POST.get('nombre', '').strip()
    if not nombre:
        return JsonResponse({'ok': False, 'error': 'El nombre es obligatorio'})
    if Materia.objects.filter(nombre__iexact=nombre).exclude(id=materia_id).exists():
        return JsonResponse({'ok': False, 'error': 'Ya existe esa materia'})
    color = request.POST.get('color', '').strip()
    materia.nombre = nombre
    if color and _HEX_COLOR_RE.match(color):
        materia.color = color
    materia.save()
    return JsonResponse({'ok': True, 'nombre': materia.nombre, 'color': materia.color})


@solo_superusuario
@rate_limit(max_calls=120, periodo=60)
def ajax_eliminar_materia(request, materia_id):
    """Elimina una materia solo si no tiene unidades asociadas.

    Unidad.materia usa on_delete=PROTECT, por lo que intentar borrar una materia
    con unidades lanzaría IntegrityError. Se valida antes para dar un error legible.
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)
    materia = get_object_or_404(Materia, id=materia_id)
    if materia.unidades.exists():
        return JsonResponse({'ok': False, 'error': 'No se puede eliminar: tiene unidades asociadas'})
    materia.delete()
    return JsonResponse({'ok': True})


# ─────────────────────────────────────────────────────────────
# AJAX GEO: Departamentos y Ciudades de Colombia
# ─────────────────────────────────────────────────────────────

@login_required
@rate_limit(max_calls=120, periodo=60)
def ajax_ciudades(request):
    """Retorna las ciudades de un departamento en formato JSON."""
    departamento = request.GET.get('departamento', '')
    ciudades     = ciudades_de(departamento)
    return JsonResponse({'ciudades': ciudades})


# ─────────────────────────────────────────────────────────────
# COLEGIOS
# ─────────────────────────────────────────────────────────────

@solo_superusuario
def configuracion_colegios(request):
    """
    Gestión de colegios y sus años académicos.

    5 acciones POST:
      - add: crea Colegio + ColegioAnio inicial.
      - edit: actualiza datos del Colegio permanente (nombre, ciudad, etc.).
      - nuevo_anio: crea un ColegioAnio adicional para un año dado.
      - toggle_activo: activa/desactiva un ColegioAnio sin borrar sus datos.
      - del: elimina el Colegio y en cascada todos sus ColegioAnio.

    El botón "Clonar para [año+1]" está en el modal "Gestionar Años" de este
    template y llama a ajax_clonar_colegio (en colegios/views.py), no a esta vista.
    """
    anio_actual = date.today().year

    if request.method == 'POST':
        accion = request.POST.get('accion', 'add')

        if accion == 'edit':
            col  = get_object_or_404(Colegio, id=request.POST.get('colegio_id'))
            form = ColegioForm(request.POST, instance=col)
            if form.is_valid():
                form.save()

        elif accion == 'toggle_activo':
            ca = get_object_or_404(ColegioAnio, id=request.POST.get('colegio_anio_id'))
            ca.activo = not ca.activo
            ca.save()

        elif accion == 'nuevo_anio':
            col = get_object_or_404(Colegio, id=request.POST.get('colegio_id'))
            try:
                nuevo_anio = int(request.POST.get('nuevo_anio', anio_actual + 1))
                if not 2000 <= nuevo_anio <= 2100:
                    raise ValueError
            except (ValueError, TypeError):
                return redirect('configuracion_colegios')
            if not ColegioAnio.objects.filter(colegio=col, anio=nuevo_anio).exists():
                ColegioAnio.objects.create(
                    colegio = col,
                    anio    = nuevo_anio,
                    activo  = True,
                )

        elif accion == 'del':
            Colegio.objects.filter(id=request.POST.get('colegio_id')).delete()

        else:  # add
            form = ColegioForm(request.POST)
            if form.is_valid():
                colegio = form.save()
                try:
                    anio = int(request.POST.get('anio', anio_actual))
                    if not 2000 <= anio <= 2100:
                        raise ValueError
                except (ValueError, TypeError):
                    anio = anio_actual
                ColegioAnio.objects.create(colegio=colegio, anio=anio, activo=True)

        return redirect('configuracion_colegios')

    # GET — colegios con sus anios
    anios_disponibles = sorted(set(
        ColegioAnio.objects.values_list('anio', flat=True)
    ), reverse=True)
    colegios = Colegio.objects.prefetch_related(
        Prefetch('anios', queryset=ColegioAnio.objects.order_by('-anio'), to_attr='anios_ordered')
    ).order_by('nombre')

    # Anotar cada colegio con datos precalculados para el template
    for c in colegios:
        todos = c.anios_ordered
        c.todos_anios = todos
        c.anios_activos = [ca for ca in todos if ca.activo]
        c.ultimo_anio_activo = next((ca for ca in todos if ca.activo), None)
        c.anios_json = json.dumps([
            {'id': ca.id, 'anio': ca.anio, 'activo': ca.activo} for ca in todos
        ])

    # Valores únicos para los filtros Select2
    codigos       = sorted(set(c for c in colegios.values_list('codigo', flat=True) if c))
    nombres       = sorted(set(colegios.values_list('nombre', flat=True)))
    departamentos = sorted(set(colegios.values_list('departamento', flat=True)))
    ciudades      = sorted(set(colegios.values_list('ciudad', flat=True)))

    return render(request, 'configuracion/colegios.html', {
        'form':               ColegioForm(),
        'colegios':           colegios,
        'anio_actual':        anio_actual,
        'anios_disponibles':  anios_disponibles,
        'codigos':            codigos,
        'nombres':            nombres,
        'departamentos':      departamentos,
        'ciudades':           ciudades,
        'departamentos_json': DEPARTAMENTOS_CIUDADES,
    })


# ─────────────────────────────────────────────────────────────
# PROFESORES
# ─────────────────────────────────────────────────────────────

@solo_superusuario
def configuracion_profesores(request):
    """
    Gestión del catálogo global de profesores.

    4 acciones POST: add, edit, toggle_activo, del.
    Los cambios de editar/crear/eliminar se registran en HistorialCambio
    para trazabilidad (solo profesores, no materias ni colegios aquí).
    """
    if request.method == 'POST':
        accion = request.POST.get('accion', 'add')

        if accion == 'edit':
            p    = get_object_or_404(Profesor, id=request.POST.get('profesor_id'))
            form = ProfesorForm(request.POST, instance=p)
            if form.is_valid():
                form.save()
                registrar_cambio(request, 'editar', p)

        elif accion == 'toggle_activo':
            p = get_object_or_404(Profesor, id=request.POST.get('profesor_id'))
            p.activo = not p.activo
            p.save()

        elif accion == 'del':
            p_del = Profesor.objects.filter(id=request.POST.get('profesor_id')).first()
            if p_del:
                registrar_cambio(request, 'eliminar', p_del)
            Profesor.objects.filter(id=request.POST.get('profesor_id')).delete()

        else:  # add
            form = ProfesorForm(request.POST)
            if form.is_valid():
                form.save()
                registrar_cambio(request, 'crear', form.instance)

        return redirect('configuracion_profesores')

    profesores = Profesor.objects.prefetch_related('materias').order_by('nombre')

    # Valores únicos para los filtros
    nombres       = sorted(set(f"{p.nombre.split()[0]} {p.apellido.split()[0]}".strip()
                               if p.apellido else p.nombre.split()[0]
                               for p in profesores))
    documentos    = sorted(set(p.documento for p in profesores if p.documento))
    ciudades_p    = sorted(set(p.ciudad for p in profesores if p.ciudad))
    deptos_p      = sorted(set(p.departamento for p in profesores if p.departamento))

    form_choices = {
        'estado_civil':  Profesor.EstadoCivil.choices,
        'eps':           Profesor.Eps.choices,
        'fondo_pension': Profesor.FondoPension.choices,
        'banco':         Profesor.Banco.choices,
        'tipo_cuenta':   Profesor.TipoCuenta.choices,
    }

    return render(request, 'configuracion/profesores.html', {
        'profesores':            profesores,
        'nombres':               nombres,
        'documentos':            documentos,
        'ciudades_p':            ciudades_p,
        'deptos_p':              deptos_p,
        'form_choices':          form_choices,
        'todas_materias':        Materia.objects.all(),
        'departamentos_json':    DEPARTAMENTOS_CIUDADES,
        'departamentos':         DEPARTAMENTOS,
    })