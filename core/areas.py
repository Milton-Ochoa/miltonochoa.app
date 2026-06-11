"""Registro de áreas AAMO y utilidades de URL **entre subdominios**.

Cada área del edificio AAMO se sirve en su propio subdominio
(`programacion.miltonochoa.app`, `logistica.miltonochoa.app`, …) en lugar de un
prefijo de ruta (`/programacion/`). El apex (`miltonochoa.app`) es el login único
y el selector de área.

Como cada host usa su propio `urlconf` (ver `core.middleware`), `{% url %}` y
`reverse()` solo resuelven los nombres del host actual. Para construir enlaces o
redirects que **cruzan** de un host a otro (p. ej. tras el login, enviar al área
correcta) usamos los helpers `url_en_area` / `url_apex`, que resuelven la ruta en
el urlconf del destino con `reverse(..., urlconf=...)` y le anteponen el host
absoluto (esquema + subdominio + puerto).
"""
from django.conf import settings
from django.urls import reverse

# Registro único de áreas. Para añadir 'logistica'/'financiera' basta con
# registrar aquí su urlconf y crear el grupo de permisos 'area:<slug>'.
#   - slug:    subdominio del área.
#   - nombre:  etiqueta legible (selector de área).
#   - urlconf: módulo de rutas que se monta en la raíz de ese subdominio.
#   - landing: nombre de URL al que se entra por defecto al abrir el área.
AREAS = {
    'programacion': {
        'slug': 'programacion',
        'nombre': 'Programación',
        'urlconf': 'core.urls_programacion',
        'landing': 'home',
    },
    'financiera': {
        'slug': 'financiera',
        'nombre': 'Financiera',
        'urlconf': 'core.urls_financiera',
        'landing': 'fin_home',
    },
    'logistica': {
        'slug': 'logistica',
        'nombre': 'Logística',
        'urlconf': 'core.urls_logistica',
        'landing': 'log_home',
    },
}

# Grupo que actúa como "etiqueta" de acceso staff al área programación: sus miembros
# usan la app completa (igual que un superusuario dentro del área) pero NO son admin
# (sin gestión de usuarios, sin /admin/ de Django, sin otras áreas).
GRUPO_STAFF_PROGRAMACION = 'area:programacion'

# Grupo de acceso al área financiera. Por ahora la asignación de usuarios a este
# grupo se hace desde /admin/ (no hay CRUD propio todavía).
GRUPO_STAFF_FINANCIERA = 'area:financiera'

# Grupo de acceso al área logística (inventario). Sus usuarios de etiqueta se
# gestionan desde el panel del apex (GRUPOS_ETIQUETA en usuarios.views).
GRUPO_STAFF_LOGISTICA = 'area:logistica'


def es_personal_programacion(user) -> bool:
    """Superusuario o miembro del grupo staff del área programación.

    Predicado único para los gates de página del área: permite abrir todas las
    vistas a la vez (configuración, exportar, vista general, etc.) cambiando un
    solo punto. Las acciones destructivas/admin siguen gated a `is_superuser`.
    """
    return bool(user.is_superuser or (
        user.is_authenticated
        and user.groups.filter(name=GRUPO_STAFF_PROGRAMACION).exists()
    ))


def es_personal_financiera(user) -> bool:
    """Superusuario o miembro del grupo de acceso al área financiera.

    Espejo de `es_personal_programacion` para el subdominio financiera; gate único
    de sus vistas (Inicio, gestión de viáticos).
    """
    return bool(user.is_superuser or (
        user.is_authenticated
        and user.groups.filter(name=GRUPO_STAFF_FINANCIERA).exists()
    ))


def es_personal_logistica(user) -> bool:
    """Superusuario o miembro del grupo de acceso al área logística.

    Espejo de `es_personal_financiera` para el subdominio logistica; gate único
    de sus vistas (inventario).
    """
    return bool(user.is_superuser or (
        user.is_authenticated
        and user.groups.filter(name=GRUPO_STAFF_LOGISTICA).exists()
    ))


def _puerto(request) -> str:
    """Puerto del host actual ('' o p. ej. '8000'). Se conserva en dev (lvh.me:8000)."""
    return request.get_host().partition(':')[2]


def host_apex(request) -> str:
    """Host del apex con su puerto: 'miltonochoa.app' o 'lvh.me:8000'."""
    puerto = _puerto(request)
    return f'{settings.BASE_DOMAIN}:{puerto}' if puerto else settings.BASE_DOMAIN


def host_de_area(slug: str, request) -> str:
    """Host del subdominio del área con su puerto: 'programacion.miltonochoa.app'."""
    puerto = _puerto(request)
    base = f'{slug}.{settings.BASE_DOMAIN}'
    return f'{base}:{puerto}' if puerto else base


def url_apex(name: str, request, *args, **kwargs) -> str:
    """URL absoluta a una vista del apex (login, seleccion_area)."""
    path = reverse(name, urlconf=settings.ROOT_URLCONF, args=args, kwargs=kwargs)
    return f'{request.scheme}://{host_apex(request)}{path}'


def url_en_area(slug: str, name: str, request, *args, **kwargs) -> str:
    """URL absoluta a una vista de otra área (resuelta en su propio urlconf)."""
    urlconf = AREAS[slug]['urlconf']
    path = reverse(name, urlconf=urlconf, args=args, kwargs=kwargs)
    return f'{request.scheme}://{host_de_area(slug, request)}{path}'


def url_landing_area(slug: str, request) -> str:
    """URL absoluta a la landing del área (su home)."""
    return url_en_area(slug, AREAS[slug]['landing'], request)


def areas_del_usuario(user):
    """Áreas a las que el usuario tiene acceso (lista de dicts de AREAS).

    Reglas (lo más simple posible, documentado para escalar a logistica/financiera):
      - Superusuario → todas las áreas.
      - Acceso a 'programacion' si: pertenece al grupo 'area:programacion', o ya
        tiene un perfil de colegio/profesor (conceptos de programacion).

    Al añadir nuevas áreas, basta con crear su grupo 'area:<slug>' y registrarla
    en AREAS (más, aquí, su condición de acceso).
    """
    if user.is_superuser:
        return list(AREAS.values())

    from usuarios.models import UsuarioColegio, UsuarioProfesor  # import diferido: evita circular

    areas = []
    tiene_programacion = (
        user.groups.filter(name=GRUPO_STAFF_PROGRAMACION).exists()
        or UsuarioColegio.objects.filter(user=user).exists()
        or UsuarioProfesor.objects.filter(user=user).exists()
    )
    if tiene_programacion:
        areas.append(AREAS['programacion'])
    if user.groups.filter(name=GRUPO_STAFF_FINANCIERA).exists():
        areas.append(AREAS['financiera'])
    if user.groups.filter(name=GRUPO_STAFF_LOGISTICA).exists():
        areas.append(AREAS['logistica'])
    return areas
