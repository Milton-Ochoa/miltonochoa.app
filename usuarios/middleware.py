from django.shortcuts import redirect
from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse
from django.contrib.auth import logout

RUTAS_PUBLICAS = ['/configuracion/usuarios/login/', '/configuracion/usuarios/logout/', '/admin/']

# La API REST usa JWT propio — DRF maneja auth y permisos internamente.
# El ControlAccesoMiddleware no aplica a estas rutas.
_RUTAS_API = ['/api/']

# Recursos PWA: el navegador los pide sin cookies/sesión activa.
_RUTAS_PWA = ['/manifest.json', '/sw.js']

# Allocated once at import time, not on every request.
_PERMITIDAS_COLEGIO  = ['/colegios/', '/informes/']
_PERMITIDAS_PROFESOR = ['/profesores/', '/informes/', '/informes/ajax/']


class ControlAccesoMiddleware:
    """
    Control de acceso por rol para todos los paths no públicos.

    Niveles de acceso (en orden de evaluación):
      - No autenticado   → redirige a login con ?next=
      - Superusuario     → acceso irrestricto; inyecta perfil_colegio=None, perfil_profesor=None
      - UsuarioColegio   → solo /colegios/ e /informes/; inyecta colegio_anio_activo (último año activo)
      - UsuarioProfesor  → solo /profesores/ e /informes/; inyecta perfil_profesor
      - Autenticado sin perfil vinculado → fuerza logout (sesión fantasma sin rol definido)

    El scope de colegio/profesor se impone por vista usando los atributos inyectados
    (`request.perfil_colegio`, `request.perfil_profesor`, `request.colegio_anio_activo`),
    no por este middleware — que solo controla a qué prefijos de URL puede acceder.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        login_url = reverse('login')

        if (any(path.startswith(r) for r in RUTAS_PUBLICAS)
                or any(path.startswith(r) for r in _RUTAS_API)
                or any(path == r for r in _RUTAS_PWA)
                or path.startswith('/static/')
                or path.startswith('/media/')):
            return self.get_response(request)

        if not request.user.is_authenticated:
            return redirect(f'{login_url}?next={path}')

        if request.user.is_superuser:
            request.perfil_colegio  = None
            request.perfil_profesor = None
            return self.get_response(request)

        try:
            from programacion.configuracion.models import ColegioAnio  # import diferido: evita circular import al cargar el módulo
            perfil = request.user.perfil_colegio
            request.perfil_colegio  = perfil
            request.perfil_profesor = None

            colegio_anio = (
                perfil.colegio.anios
                .filter(activo=True)
                .order_by('-anio')
                .first()
            )
            request.colegio_anio_activo = colegio_anio

            if not any(path.startswith(r) for r in _PERMITIDAS_COLEGIO):
                id_col = colegio_anio.id if colegio_anio else ''
                return redirect(f'{reverse("dashboard")}?id_col={id_col}')

            return self.get_response(request)
        except ObjectDoesNotExist:
            pass

        try:
            perfil = request.user.perfil_profesor
            request.perfil_colegio  = None
            request.perfil_profesor = perfil

            if not any(path.startswith(r) for r in _PERMITIDAS_PROFESOR):
                return redirect(f'{reverse("ver_horario")}?profesor_id={perfil.profesor.id}')

            return self.get_response(request)
        except ObjectDoesNotExist:
            pass

        # Usuario autenticado sin perfil vinculado → forzar logout para evitar sesión sin rol
        logout(request)
        return redirect(login_url)