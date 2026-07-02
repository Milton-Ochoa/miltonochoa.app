from urllib.parse import urlencode

from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse
from django.contrib.auth import logout

from core.areas import AREAS, url_apex

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

    def _bloqueo_escritura(self, request):
        """Respuesta 403 para una escritura sobre un módulo en modo LECTURA.

        Fetch/XHR (Sec-Fetch-Mode presente y ≠ 'navigate') → JSON, para que el JS de
        área existente muestre `data.error`; navegación normal → página 403 standalone.
        NUNCA usa `messages` (financiera prohíbe toasts; la página es autónoma).
        """
        if request.headers.get('Sec-Fetch-Mode') not in (None, 'navigate'):
            return JsonResponse(
                {'ok': False, 'error': 'Tu acceso a este módulo es de solo lectura.'},
                status=403)
        return render(request, 'core/403_modulo.html', status=403)

    def _gate_modulo(self, request, area, path, modulos):
        """Enforcement granular por módulo dentro de un área.

        `modulos` = {slug: nivel} ya resuelto (base por grupo + overrides). Devuelve la
        respuesta de bloqueo (redirect/403) o None si la petición puede seguir. Las
        exenciones y el núcleo pasan siempre; una ruta no catalogada se trata como núcleo
        (retrocompatible: sin overrides todo queda COMPLETO y esto es inerte).
        """
        from core.modulos import EXENTAS, NUCLEO, es_raiz, modulo_de_path
        from usuarios.permisos import COM, LEC, SIN

        if any(path.startswith(e) for e in EXENTAS):
            return None
        if es_raiz(path) or any(path.startswith(n) for n in NUCLEO.get(area, ())):
            return None
        mod = modulo_de_path(area, path)
        if mod is None:                     # no catalogado → núcleo/infra
            return None
        nivel = modulos.get(mod.slug, SIN)
        if nivel == COM:
            return None
        if nivel == LEC:
            if request.method in ('GET', 'HEAD', 'OPTIONS'):
                return None
            if path in mod.posts_lectura:   # exports (POST de lectura), igualdad EXACTA
                return None
            return self._bloqueo_escritura(request)
        # SIN acceso al módulo → de vuelta a la landing del área (bucle-safe: es núcleo).
        return redirect(reverse(AREAS[area]['landing'], urlconf=request.urlconf))

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

        # Banderas por defecto para las plantillas (cada rama de área sube la suya a True).
        request.es_personal_programacion = False
        request.es_personal_financiera = False
        request.es_personal_logistica = False
        request.modulos = {}
        request.modulos_permitidos = set()

        from usuarios.permisos import SIN, resolver_acceso_area

        # ── Áreas financiera / logistica ──
        # Acceso por grupo 'area:<area>' (o superusuario) o por overrides cruzados. El
        # subdominio no tiene perfiles de colegio/profesor: cualquier otro autenticado se
        # manda al selector de área del apex (no se le hace logout: puede tener otra área).
        if request.area in ('financiera', 'logistica'):
            acceso, modulos = resolver_acceso_area(request.user, request.area)
            if not acceso:
                return redirect(url_apex('seleccion_area', request))
            request.perfil_colegio  = None
            request.perfil_profesor = None
            setattr(request, f'es_personal_{request.area}', True)
            request.modulos = modulos
            request.modulos_permitidos = {s for s, n in modulos.items() if n != SIN}
            bloqueo = self._gate_modulo(request, request.area, path, modulos)
            if bloqueo is not None:
                return bloqueo
            return self.get_response(request)

        # ── Área programacion ──
        # Superusuario, staff (grupo 'area:programacion') y acceso cruzado por overrides se
        # unifican: la resolución devuelve todo COMPLETO al superuser/grupo y solo los
        # módulos cruzados al usuario con overrides. Va antes de los perfiles colegio/
        # profesor para que un usuario "solo etiqueta/override" (sin perfil) no caiga en el
        # logout final; el gate por módulo recorta dentro del área.
        acceso, modulos = resolver_acceso_area(request.user, 'programacion')
        if acceso:
            request.perfil_colegio  = None
            request.perfil_profesor = None
            request.es_personal_programacion = True
            request.modulos = modulos
            request.modulos_permitidos = {s for s, n in modulos.items() if n != SIN}
            bloqueo = self._gate_modulo(request, 'programacion', path, modulos)
            if bloqueo is not None:
                return bloqueo
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
