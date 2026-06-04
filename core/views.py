import calendar
from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.db.models import Q
from datetime import date
from collections import defaultdict

from programacion.colegios.models import HistorialCambio, Bloque, Clase
from programacion.colegios.historial import aplicar_filtros_historial
from programacion.colegios.utils import extraer_numero_grado, ordenar_grados
from programacion.configuracion.models import Colegio, ColegioAnio, Profesor


def home(request):
    return render(request, 'home.html')


# ── Enrutado por áreas (login único AAMO) ───────────────────────────────────
# El registro de áreas y los helpers de URL entre subdominios viven en core.areas.
from core.areas import areas_del_usuario, url_landing_area, es_personal_programacion  # noqa: E402


@login_required
def seleccion_area(request):
    """Punto de entrada AAMO (apex) tras el login.

    - Superusuario      → panel de administración (acceso a todas las áreas + gestión).
    - Sin área asignada → mensaje claro (403).
    - Una sola área     → redirige directo a su subdominio (URL absoluta).
    - Varias áreas      → página de selección con enlaces a cada subdominio.
    """
    if request.user.is_superuser:
        return redirect('panel_admin')
    areas = areas_del_usuario(request.user)
    if not areas:
        return render(request, 'core/sin_area.html', status=403)
    if len(areas) == 1:
        return redirect(url_landing_area(areas[0]['slug'], request))
    areas_ctx = [
        {'nombre': a['nombre'], 'url': url_landing_area(a['slug'], request)}
        for a in areas
    ]
    return render(request, 'core/seleccion_area.html', {'areas': areas_ctx})


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def panel_admin(request):
    """Panel del superusuario (apex). Único punto de entrada para el admin.

    Reúne el acceso a todas las áreas registradas (URL absoluta a la landing de cada
    subdominio) y la gestión de usuarios de etiqueta (CRUD vía AJAX en usuarios.views).
    Solo superusuarios; los usuarios de etiqueta van directo a su área, no aquí.
    """
    from core.areas import AREAS
    from django.contrib.auth.models import User

    areas_ctx = [
        {'nombre': a['nombre'], 'slug': a['slug'],
         'url': url_landing_area(a['slug'], request)}
        for a in AREAS.values()
    ]
    usuarios_etiqueta = (
        User.objects
        .filter(groups__name='area:programacion')
        .order_by('username')
    )
    usuarios_etiqueta_financiera = (
        User.objects
        .filter(groups__name='area:financiera')
        .order_by('username')
    )
    return render(request, 'core/panel_admin.html', {
        'areas': areas_ctx,
        'usuarios_etiqueta': usuarios_etiqueta,
        'usuarios_etiqueta_financiera': usuarios_etiqueta_financiera,
    })


@user_passes_test(es_personal_programacion, login_url='login')
def historial_global(request):
    """
    Historial de cambios de todo el sistema (todos los colegios), paginado server-side.

    Disponible solo para superusuarios. Los gestores de colegio usan
    historial_colegio (en colegios/views.py) con scope limitado a su colegio.
    Los mismos filtros de aplicar_filtros_historial aplican en ambas vistas.
    """
    from django.core.paginator import Paginator
    qs = HistorialCambio.objects.select_related('colegio__colegio', 'usuario')
    qs, filtros = aplicar_filtros_historial(qs, request.GET)
    qs = qs.order_by('-fecha')
    paginator  = Paginator(qs, 10)
    page_obj   = paginator.get_page(request.GET.get('page', 1))
    return render(request, 'core/historial_global.html', {
        'cambios':  page_obj,
        'page_obj': page_obj,
        **filtros,
    })


_VG_TTL = 600  # segundos — 10 min reduce frecuencia de regeneración


def _vg_cache_key(anio: int, mes: int) -> str:
    return f'vista_general:{anio}:{mes}'


def invalidar_vista_general():
    """Borra entradas de caché de vista_general para todos los meses de cada año
    presente en ColegioAnio (más el año actual por defecto).

    Llamado desde colegios/signals.py al modificar Clase o Asignacion.
    Funciona con locmem (cache.delete por clave) y con Redis (misma API).
    """
    anios = set(ColegioAnio.objects.values_list('anio', flat=True))
    anios.add(date.today().year)
    for anio in anios:
        for mes in range(1, 13):
            cache.delete(_vg_cache_key(anio, mes))


@login_required
def vista_general(request):
    """
    Calendario unificado de todos los colegios activos del año en curso.

    Filtra por mes (?mes=1..12, default=mes actual) para evitar cargar las
    2000+ clases anuales de golpe. Usa .values() en vez de instanciar modelos
    completos — más rápido y suficiente para lectura del cronograma.

    nombre_corto se calcula en Python porque Profesor.nombre_corto es @property
    y no está disponible en consultas .values().
    """
    hoy = date.today()

    # Años disponibles: distintos en ColegioAnio activos. Garantizar que el año
    # actual aparezca aunque no haya colegios cargados todavía.
    anios_disponibles = sorted(
        set(ColegioAnio.objects.filter(activo=True).values_list('anio', flat=True)) | {hoy.year},
        reverse=True,
    )

    # Filtro por año: default = año actual
    try:
        anio_actual = int(request.GET.get('anio', hoy.year))
        if anio_actual not in anios_disponibles:
            anio_actual = hoy.year
    except (ValueError, TypeError):
        anio_actual = hoy.year

    # Filtro por mes: default = mes actual
    try:
        mes_sel = int(request.GET.get('mes', hoy.month))
        if not 1 <= mes_sel <= 12:
            mes_sel = hoy.month
    except (ValueError, TypeError):
        mes_sel = hoy.month

    # Caché: guardamos bytes del HTML renderizado para evitar reconstruir el
    # contexto (con sus instancias de modelo) en cada request.
    # La clave es predecible → signals.py puede invalidarla exactamente.
    ck = _vg_cache_key(anio_actual, mes_sel)
    cached_html = cache.get(ck)
    if cached_html is not None:
        return HttpResponse(cached_html, content_type='text/html; charset=utf-8')

    todos_bloques = (
        Bloque.objects
        .filter(colegio__activo=True, colegio__anio=anio_actual)
        .select_related('colegio__colegio', 'grado')
        .order_by('colegio__colegio__nombre', 'hora_inicio')
    )

    # Agrupar: Colegio → grado_nombre → [bloques]
    temp_agrupado = defaultdict(lambda: defaultdict(list))
    for bloque in todos_bloques:
        temp_agrupado[bloque.colegio][bloque.grado.nombre].append(bloque)

    estructura_general = []
    all_bloque_ids = []
    for colegio in sorted(temp_agrupado.keys(), key=lambda c: c.nombre):
        datos_colegio = {
            'colegio':       colegio,
            'grados_data':   [],
            'total_rowspan': 0,
        }

        grados_dict    = temp_agrupado[colegio]
        grados_ordenados = ordenar_grados(grados_dict.keys())

        for grado_nombre in grados_ordenados:
            bloques_ordenados = sorted(
                grados_dict[grado_nombre],
                key=lambda x: (x.hora_inicio.hour * 60 + x.hora_inicio.minute)
                              if x.hora_inicio else 0
            )
            rowspan_grado = len(bloques_ordenados)
            datos_colegio['grados_data'].append({
                'nombre_grado': grado_nombre,
                'bloques':      bloques_ordenados,
                'rowspan':      rowspan_grado,
            })
            datos_colegio['total_rowspan'] += rowspan_grado
            all_bloque_ids.extend(b.id for b in bloques_ordenados)

        if len(grados_ordenados) > 1:
            datos_colegio['total_rowspan'] += (len(grados_ordenados) - 1)

        estructura_general.append(datos_colegio)

    # Solo cargar clases del mes seleccionado — valores planos (más rápido que instanciar modelos)
    inicio = date(anio_actual, mes_sel, 1)
    fin    = date(anio_actual, mes_sel, calendar.monthrange(anio_actual, mes_sel)[1])
    clases_raw = Clase.objects.filter(
        bloque_id__in=all_bloque_ids,
        fecha__range=[inicio, fin],
    ).values(
        'bloque_id', 'fecha', 'unidad', 'es_evento', 'cancelada',
        'titulo_evento', 'libro_especial_id',
        'profesor__nombre', 'profesor__apellido',
        'materia__nombre',
    )

    def _nombre_corto(nombre, apellido):
        """Replica la lógica de Profesor.nombre_corto sobre valores planos de .values()."""
        p1 = nombre.split()[0] if nombre else ''
        p2 = apellido.split()[0] if apellido else ''
        return f"{p1} {p2}".strip()

    matriz = defaultdict(dict)
    for c in clases_raw:
        c['profesor__nombre_corto'] = _nombre_corto(c['profesor__nombre'], c['profesor__apellido'])
        matriz[c['bloque_id']][str(c['fecha'])] = c

    # Solo fechas que realmente tienen clases
    fechas_con_clases = sorted({
        fecha_str
        for bloque_dict in matriz.values()
        for fecha_str in bloque_dict.keys()
    })

    MESES_ES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
    ctx = {
        'dias_header':        [date.fromisoformat(f) for f in fechas_con_clases],
        'estructura_general': estructura_general,
        'matriz':             matriz,
        'hoy':                hoy.isoformat(),
        'mes_sel':            mes_sel,
        'meses':              [(i, MESES_ES[i]) for i in range(1, 13)],
        'anio_sel':           anio_actual,
        'anios':              anios_disponibles,
    }
    response = render(request, 'general/vista_general.html', ctx)
    # Guardamos bytes (str serializable) — compatible con locmem y Redis.
    # El HTML de vista_general no varía por usuario (solo superusers lo ven,
    # todos ven los mismos datos) y no contiene formularios con CSRF.
    cache.set(ck, response.content, _VG_TTL)
    return response


@login_required
@user_passes_test(es_personal_programacion, login_url='login')
def ajax_busqueda_global(request):
    """Búsqueda global de colegios y profesores. Devuelve fragmento HTML para HTMX."""
    q = request.GET.get('q', '').strip()
    results = []

    if len(q) >= 2:
        # Cada palabra de la consulta debe casar (AND entre palabras), pero puede
        # hacerlo contra cualquiera de los campos buscables (OR dentro de la palabra).
        # Así "Luis Galeano" encuentra a quien tenga "Luis" en nombre y "Galeano" en
        # apellido, en cualquier orden, y un colegio se halla por nombre o por código.
        palabras = q.split()

        # Colegios activos del año en curso (por nombre o código)
        anio_actual = date.today().year
        filtro_col = Q()
        for palabra in palabras:
            filtro_col &= (Q(colegio__nombre__icontains=palabra) |
                           Q(colegio__codigo__icontains=palabra))
        colegios = (
            ColegioAnio.objects
            .filter(filtro_col, anio=anio_actual, activo=True)
            .select_related('colegio')
            .order_by('colegio__nombre')[:6]
        )
        url_colegios = reverse('dashboard')
        for ca in colegios:
            # Mismo formato que el dashboard: "[código] - [nombre]" si hay código.
            etiqueta = f'{ca.codigo} - {ca.nombre}' if ca.codigo else ca.nombre
            results.append({
                'tipo': 'Colegio',
                'nombre': etiqueta,
                'url': f'{url_colegios}?id_col={ca.pk}',
                'icon': 'fa-school',
            })

        # Profesores (por cualquier combinación de palabras de nombre/apellido)
        filtro_prof = Q()
        for palabra in palabras:
            filtro_prof &= (Q(nombre__icontains=palabra) | Q(apellido__icontains=palabra))
        profesores = (
            Profesor.objects
            .filter(filtro_prof)
            .order_by('nombre', 'apellido')[:6]
        )
        url_profesores = reverse('ver_horario')
        for p in profesores:
            nombre_completo = f"{p.nombre} {p.apellido}".strip()
            results.append({
                'tipo': 'Profesor',
                'nombre': nombre_completo,
                'url': f'{url_profesores}?profesor_id={p.pk}',
                'icon': 'fa-user-tie',
            })

    return render(request, 'core/_partials/_search_results.html', {'results': results, 'q': q})


def manifest_view(request):
    """Web App Manifest para PWA. Devuelve application/manifest+json."""
    data = {
        "name": "Programación AAMO",
        "short_name": "AAMO",
        "description": "Sistema de gestión de colegios AAMO",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#f4f6f9",
        "theme_color": "#212529",
        "icons": [
            {
                "src": "/static/img/logo_color.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable",
            }
        ],
    }
    return JsonResponse(data, content_type='application/manifest+json')


def sw_view(request):
    """Service worker para PWA. Debe servirse desde la raíz (scope /)."""
    from django.template.response import TemplateResponse
    return TemplateResponse(request, 'sw.js', {}, content_type='application/javascript')


def error_404(request, exception=None):
    return render(request, '404.html', status=404)


def error_500(request):
    return render(request, '500.html', status=500)