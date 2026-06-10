from urllib.parse import urlencode

from django.shortcuts import redirect
from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse
from django.contrib.auth import logout

from core.areas import url_apex, GRUPO_STAFF_PROGRAMACION, GRUPO_STAFF_FINANCIERA

# '/usuarios/telemetria/': el capturador de errores del navegador debe poder reportar desde
# cualquier rol (incluidos colegio/profesor, restringidos a sus prefijos) y aun sin sesión.
RUTAS_PUBLICAS = ['/usuarios/login/', '/usuarios/logout/', '/usuarios/telemetria/', '/admin/']

# Recursos PWA: el navegador los pide sin cookies/sesión activa.
_RUTAS_PWA = ['/manifest.json', '/sw.js']

# Allocated once at import time, not on every request.
# Prefijos del área programacion a los que cada rol tiene acceso (en la raíz del subdominio).
_PERMITIDAS_COLEGIO  = ['/colegios/', '/informes/']
_PERMITIDAS_PROFESOR = ['/profesores/', '/informes/']


class ControlAccesoMiddleware:
    """
    Control de acceso por rol dentro de un **subdominio de área**.

    Solo actúa cuando la petición va dirigida a un área (`request.area` definido por
    EnrutadoPorAreaMiddleware). En el apex (login único, selector de área) deja pasar:
    esas vistas se protegen con sus propios decoradores (`@login_required`, etc.).

    Niveles de acceso (en orden de evaluación, dentro del área):
      - No autenticado   → redirige al login del APEX con ?next= (URL absoluta)
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

    def _redir_cambio_password(self, request):
        """Redirige a la página de cambio obligatorio si el usuario es un empleado con
        `debe_cambiar_password=True` (y no está ya en ella). None si no aplica.

        Solo los empleados de área tienen `PerfilEmpleado`; superusuarios y perfiles de
        colegio/profesor no lo tienen → no se les fuerza nada.
        """
        from usuarios.models import PerfilEmpleado  # import diferido: evita circular import
        debe = (PerfilEmpleado.objects
                .filter(user=request.user, debe_cambiar_password=True)
                .exists())
        if not debe:
            return None
        destino = reverse('cambiar_password', urlconf=request.urlconf)
        if request.path == destino:
            return None
        return redirect(destino)

    def __call__(self, request):
        # Apex: las vistas se protegen con decoradores. Este control es por área.
        if getattr(request, 'area', None) is None:
            return self.get_response(request)

        path = request.path

        if (any(path.startswith(r) for r in RUTAS_PUBLICAS)
                or any(path == r for r in _RUTAS_PWA)
                or path.startswith('/static/')
                or path.startswith('/media/')):
            return self.get_response(request)

        if not request.user.is_authenticated:
            # Login canónico en el apex; volver a la URL solicitada tras autenticar.
            login_apex = url_apex('login', request)
            next_abs = request.build_absolute_uri()
            return redirect(f'{login_apex}?{urlencode({"next": next_abs})}')

        # Empleado de área con clave genérica pendiente de cambio: bloquea todo el área
        # hasta que elija su propia contraseña (salvo la propia página de cambio).
        redir_cambio = self._redir_cambio_password(request)
        if redir_cambio is not None:
            return redir_cambio

        # Bandera por defecto para las plantillas (la rama de financiera la sube a True).
        request.es_personal_financiera = False

        # ── Área financiera ──
        # Acceso por grupo 'area:financiera' (o superusuario). El subdominio no tiene
        # perfiles de colegio/profesor: cualquier otro autenticado se manda al selector
        # de área del apex (no se le hace logout: puede tener acceso a otra área).
        if request.area == 'financiera':
            if request.user.is_superuser or request.user.groups.filter(name=GRUPO_STAFF_FINANCIERA).exists():
                request.perfil_colegio  = None
                request.perfil_profesor = None
                request.es_personal_programacion = False
                request.es_personal_financiera = True
                return self.get_response(request)
            return redirect(url_apex('seleccion_area', request))

        # ── Área programacion (comportamiento original) ──
        if request.user.is_superuser:
            request.perfil_colegio  = None
            request.perfil_profesor = None
            request.es_personal_programacion = True
            return self.get_response(request)

        # Staff del área (grupo 'area:programacion'): acceso pleno al área, igual que un
        # superusuario, pero sin ser admin. Va antes de los perfiles colegio/profesor para
        # que un usuario "solo etiqueta" (sin perfil) no caiga en el logout final.
        if request.user.groups.filter(name=GRUPO_STAFF_PROGRAMACION).exists():
            request.perfil_colegio  = None
            request.perfil_profesor = None
            request.es_personal_programacion = True
            return self.get_response(request)

        try:
            from programacion.configuracion.models import ColegioAnio  # import diferido: evita circular import al cargar el módulo
            perfil = request.user.perfil_colegio
            request.perfil_colegio  = perfil
            request.perfil_profesor = None
            request.es_personal_programacion = False

            colegio_anio = (
                perfil.colegio.anios
                .filter(activo=True)
                .order_by('-anio')
                .first()
            )
            request.colegio_anio_activo = colegio_anio

            if not any(path.startswith(r) for r in _PERMITIDAS_COLEGIO):
                id_col = colegio_anio.id if colegio_anio else ''
                # urlconf explícito: el thread-local aún apunta al apex en esta fase.
                destino = reverse("dashboard", urlconf=request.urlconf)
                return redirect(f'{destino}?id_col={id_col}')

            return self.get_response(request)
        except ObjectDoesNotExist:
            pass

        try:
            perfil = request.user.perfil_profesor
            request.perfil_colegio  = None
            request.perfil_profesor = perfil
            request.es_personal_programacion = False

            if not any(path.startswith(r) for r in _PERMITIDAS_PROFESOR):
                destino = reverse("ver_horario", urlconf=request.urlconf)
                return redirect(f'{destino}?profesor_id={perfil.profesor.id}')

            return self.get_response(request)
        except ObjectDoesNotExist:
            pass

        # Usuario autenticado sin perfil vinculado → forzar logout para evitar sesión sin rol
        logout(request)
        return redirect(url_apex('login', request))
