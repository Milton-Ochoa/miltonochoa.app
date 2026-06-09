from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.models import User, Group
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.decorators import user_passes_test, login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.http import JsonResponse
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST
import json
import logging

from .models import UsuarioColegio, UsuarioProfesor, PerfilEmpleado, ErrorCliente
from .ratelimit import rate_limit
from programacion.configuracion.models import Colegio, Profesor
from core.areas import (
    AREAS, url_apex, url_en_area, host_apex, host_de_area,
    GRUPO_STAFF_PROGRAMACION, GRUPO_STAFF_FINANCIERA, es_personal_programacion,
)

# Áreas cuyos usuarios de etiqueta se gestionan desde el panel del apex: slug → grupo.
# El grupo basta para que el login lleve al usuario a su subdominio (sin perfil ni is_staff).
GRUPOS_ETIQUETA = {
    'programacion': GRUPO_STAFF_PROGRAMACION,
    'financiera': GRUPO_STAFF_FINANCIERA,
}

logger = logging.getLogger('aamo')

def solo_admin(user):
    """Solo superusuario: gestión de usuarios de etiqueta y panel del apex.

    La gestión de usuarios de colegio/profesor usa `es_personal_programacion`
    (superusuario o staff del área), no este predicado.
    """
    return user.is_superuser

def _hosts_permitidos(request):
    """Hosts propios (apex + subdominios de áreas) para validar `?next=` cross-subdominio."""
    return {host_apex(request)} | {host_de_area(slug, request) for slug in AREAS}

PASSWORD_TEMPORAL_MIN = 8


def _limpiar_password_temporal(password):
    """Valida una contraseña **temporal asignada por el admin** (colegio/profesor o la
    genérica de empleado).

    A propósito NO aplica los AUTH_PASSWORD_VALIDATORS completos: el staff debe poder
    asignar la clave que quiera (los empleados igual la cambian en el primer ingreso).
    Solo se exige un mínimo de 8 caracteres: el login es público en internet y una clave
    trivial ("1234") se adivina por fuerza bruta aunque haya rate limit por IP.
    Devuelve la clave limpia o lanza ValueError con un mensaje legible.
    """
    password = (password or '').strip()
    if not password:
        raise ValueError('La contraseña es obligatoria.')
    if len(password) < PASSWORD_TEMPORAL_MIN:
        raise ValueError(f'La contraseña debe tener al menos {PASSWORD_TEMPORAL_MIN} caracteres.')
    return password


def _limpiar_email(email):
    """Valida que el correo del empleado sea obligatorio y con formato válido."""
    email = (email or '').strip()
    if not email:
        raise ValueError('El correo es obligatorio.')
    try:
        validate_email(email)
    except ValidationError:
        raise ValueError('El correo no tiene un formato válido.')
    return email

def _crear_usuario_base(username, password):
    """
    Crea el User base de Django. Debe llamarse dentro de transaction.atomic().

    Si ya existe un User con ese nombre pero sin perfil vinculado (huérfano de una
    transacción fallida anterior), lo reemplaza silenciosamente. Si tiene perfil,
    lanza ValueError para que la vista devuelva un error legible al admin.
    """
    user_existente = User.objects.filter(username=username).first()
    if user_existente:
        tiene_perfil = (
            UsuarioColegio.objects.filter(user=user_existente).exists() or
            UsuarioProfesor.objects.filter(user=user_existente).exists()
        )
        if tiene_perfil:
            raise ValueError(f'El usuario "{username}" ya está en uso.')
        user_existente.delete()
    return User.objects.create_user(username=username, password=password,
                                    is_staff=False, is_superuser=False)

def login_redirect(request):
    """Redirige al usuario autenticado a su área (subdominio) y página de rol.

    El login es del apex; el destino vive en otro host (programacion.<dominio>),
    así que se construyen URLs **absolutas** al subdominio con los helpers de
    core.areas (resuelven la ruta en el urlconf del área).
    """
    if not request.user.is_authenticated:
        return redirect('login')
    if request.user.is_superuser:
        return redirect(url_apex('panel_admin', request))
    try:
        perfil = request.user.perfil_colegio
        from programacion.configuracion.models import ColegioAnio
        ca = perfil.colegio.anios.filter(activo=True).order_by('-anio').first()
        id_col = ca.id if ca else ''
        destino = url_en_area('programacion', 'dashboard', request)
        return redirect(f'{destino}?id_col={id_col}')
    except UsuarioColegio.DoesNotExist:
        pass
    try:
        perfil = request.user.perfil_profesor
        destino = url_en_area('programacion', 'ver_horario', request)
        return redirect(f'{destino}?profesor_id={perfil.profesor.id}')
    except UsuarioProfesor.DoesNotExist:
        pass
    return redirect(url_apex('seleccion_area', request))

@rate_limit(max_calls=10, periodo=60, respuesta='html')
def vista_login(request):
    """
    Login con rate limit de 10 intentos / 60 segundos por IP.
    Post-login: redirige a ?next= si es válido y seguro, o a la página del rol.
    """
    if request.user.is_authenticated:
        return login_redirect(request)

    error = None
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            next_url = request.GET.get('next', '')
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts=_hosts_permitidos(request)):
                return redirect(next_url)
            return login_redirect(request)
        else:
            error = 'Usuario o contraseña incorrectos.'

    return render(request, 'usuarios/login.html', {'error': error})

@require_POST
def vista_logout(request):
    logout(request)
    return redirect('login')

@user_passes_test(es_personal_programacion, login_url='login')
def gestionar_colegios(request):
    """Gestión de usuarios de colegios (solo superusuario). Acciones AJAX."""
    usuarios = (UsuarioColegio.objects
                .select_related('user', 'colegio')
                .order_by('colegio__nombre', 'user__username'))
    colegios = Colegio.objects.all().order_by('nombre')
    return render(request, 'usuarios/gestionar.html', {
        'tipo': 'colegio',
        'usuarios': usuarios,
        'colegios': colegios,
    })

@user_passes_test(es_personal_programacion, login_url='login')
def gestionar_profesores(request):
    """Gestión de usuarios de profesores (solo superusuario). Acciones AJAX."""
    usuarios = (UsuarioProfesor.objects
                .select_related('user', 'profesor')
                .order_by('profesor__nombre', 'user__username'))
    profesores = Profesor.objects.all().order_by('nombre')
    return render(request, 'usuarios/gestionar.html', {
        'tipo': 'profesor',
        'usuarios': usuarios,
        'profesores': profesores,
    })

@user_passes_test(es_personal_programacion, login_url='login')
@require_POST
def ajax_crear_usuario(request):
    """
    Crea un usuario de colegio o profesor con la contraseña que asigna **manualmente** el
    staff de programación (no aleatoria). La clave no se devuelve: el admin ya la conoce.
    """
    tipo = request.POST.get('tipo')
    username = request.POST.get('username', '').strip()

    if not username or tipo not in ('colegio', 'profesor'):
        return JsonResponse({'ok': False, 'error': 'Datos inválidos.'}, status=400)

    try:
        password = _limpiar_password_temporal(request.POST.get('password'))
    except ValueError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=400)

    try:
        with transaction.atomic():
            user = _crear_usuario_base(username, password)

            if tipo == 'colegio':
                colegio_id = request.POST.get('colegio_id')
                colegio = get_object_or_404(Colegio, id=colegio_id)
                UsuarioColegio.objects.create(user=user, colegio=colegio)
                nombre_destino = colegio.nombre
                logger.info('Usuario de colegio creado: %s → %s (por %s)', username, nombre_destino, request.user.username)
            else:
                profesor_id = request.POST.get('profesor_id')
                profesor = get_object_or_404(Profesor, id=profesor_id)
                UsuarioProfesor.objects.create(user=user, profesor=profesor)
                nombre_destino = profesor.nombre_corto
                logger.info('Usuario de profesor creado: %s → %s (por %s)', username, nombre_destino, request.user.username)

    except ValueError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=400)
    except Exception:
        logger.exception('Error al crear usuario tipo=%s', tipo)
        return JsonResponse({'ok': False, 'error': 'Error interno. Intenta de nuevo.'}, status=500)

    return JsonResponse({
        'ok': True,
        'username': username,
        'nombre_destino': nombre_destino,
    })

@user_passes_test(es_personal_programacion, login_url='login')
@require_POST
def ajax_editar_usuario(request):
    """Actualiza username y/o colegio/profesor vinculado de un perfil existente."""
    tipo      = request.POST.get('tipo')
    perfil_id = request.POST.get('perfil_id')

    if tipo not in ('colegio', 'profesor') or not perfil_id:
        return JsonResponse({'ok': False, 'error': 'Datos inválidos.'}, status=400)

    modelo = UsuarioColegio if tipo == 'colegio' else UsuarioProfesor
    perfil = get_object_or_404(modelo, id=perfil_id)

    new_username = request.POST.get('username', '').strip()
    if new_username and new_username != perfil.user.username:
        if User.objects.filter(username=new_username).exclude(id=perfil.user.id).exists():
            return JsonResponse({'ok': False, 'error': f'El usuario "{new_username}" ya existe.'}, status=400)
        perfil.user.username = new_username
        perfil.user.save()

    if tipo == 'colegio':
        colegio_id = request.POST.get('colegio_id')
        if colegio_id:
            perfil.colegio = get_object_or_404(Colegio, id=colegio_id)
    else:
        profesor_id = request.POST.get('profesor_id')
        if profesor_id:
            perfil.profesor = get_object_or_404(Profesor, id=profesor_id)
    perfil.save()

    return JsonResponse({'ok': True})

@user_passes_test(es_personal_programacion, login_url='login')
@require_POST
def ajax_eliminar_usuario(request):
    """Elimina el perfil y el User asociado. Acción irreversible — registrada en el log."""
    tipo      = request.POST.get('tipo')
    perfil_id = request.POST.get('perfil_id')

    if tipo not in ('colegio', 'profesor') or not perfil_id:
        return JsonResponse({'ok': False, 'error': 'Datos inválidos.'}, status=400)

    modelo = UsuarioColegio if tipo == 'colegio' else UsuarioProfesor
    perfil = get_object_or_404(modelo, id=perfil_id)
    nombre = perfil.user.username
    user   = perfil.user
    perfil.delete()
    user.delete()
    logger.info('Usuario eliminado: %s (por %s)', nombre, request.user.username)
    return JsonResponse({'ok': True, 'username': nombre})

@user_passes_test(es_personal_programacion, login_url='login')
@require_POST
def ajax_resetear_password(request):
    """
    Asigna la nueva contraseña que escribe **manualmente** el staff a un usuario de
    colegio/profesor. Operación auditada: registra quién reseteó, a quién, y desde qué IP.
    """
    tipo      = request.POST.get('tipo')
    perfil_id = request.POST.get('perfil_id')

    if tipo not in ('colegio', 'profesor') or not perfil_id:
        return JsonResponse({'ok': False, 'error': 'Datos inválidos.'}, status=400)

    try:
        nueva = _limpiar_password_temporal(request.POST.get('password'))
    except ValueError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=400)

    modelo = UsuarioColegio if tipo == 'colegio' else UsuarioProfesor
    perfil = get_object_or_404(modelo, id=perfil_id)

    perfil.user.set_password(nueva)
    perfil.user.save()

    logger.info(
        'Contraseña reseteada: perfil %s id=%s usuario=%s (por %s desde %s)',
        tipo, perfil_id, perfil.user.username,
        request.user.username, request.META.get('REMOTE_ADDR'),
    )
    return JsonResponse({'ok': True, 'username': perfil.user.username})


# ── Usuarios de etiqueta (grupo 'area:programacion') ─────────────────────────
# A diferencia de colegio/profesor, no tienen perfil: son usuarios genéricos del área
# (acceso completo de staff, ver core.areas.es_personal_programacion). Se gestionan
# desde el panel del superusuario en el apex.

def _get_usuario_etiqueta(user_id):
    """User de cualquier grupo de etiqueta y NO superusuario; None si no aplica (evita tocar admins)."""
    if not user_id:
        return None
    return (User.objects
            .filter(id=user_id, groups__name__in=list(GRUPOS_ETIQUETA.values()), is_superuser=False)
            .first())

@user_passes_test(solo_admin, login_url='login')
@require_POST
def ajax_crear_usuario_area(request):
    """
    Crea un empleado de área (programacion/financiera) con la **clave genérica** y el
    **correo** que asigna el admin. El correo es obligatorio (lo usa "olvidé mi contraseña")
    y el empleado debe cambiar la clave en el primer ingreso (`PerfilEmpleado`).

    El usuario no es is_staff (no entra a /admin/) ni superusuario; pertenecer al grupo
    de etiqueta del área basta para que el login lo lleve a su subdominio y el middleware
    le conceda acceso completo dentro de ella.
    """
    username = request.POST.get('username', '').strip()
    area = request.POST.get('area', 'programacion').strip()
    grupo_nombre = GRUPOS_ETIQUETA.get(area)
    if not grupo_nombre:
        return JsonResponse({'ok': False, 'error': 'Área no válida.'}, status=400)
    if not username:
        return JsonResponse({'ok': False, 'error': 'El nombre de usuario es obligatorio.'}, status=400)
    if User.objects.filter(username=username).exists():
        return JsonResponse({'ok': False, 'error': f'El usuario "{username}" ya existe.'}, status=400)

    try:
        email = _limpiar_email(request.POST.get('email'))
        password = _limpiar_password_temporal(request.POST.get('password'))
    except ValueError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=400)

    try:
        with transaction.atomic():
            user = User.objects.create_user(
                username=username, password=password, email=email,
                is_staff=False, is_superuser=False,
            )
            grupo, _ = Group.objects.get_or_create(name=grupo_nombre)
            user.groups.add(grupo)
            PerfilEmpleado.objects.create(user=user, debe_cambiar_password=True)
    except Exception:
        logger.exception('Error al crear usuario de etiqueta')
        return JsonResponse({'ok': False, 'error': 'Error interno. Intenta de nuevo.'}, status=500)

    logger.info('Usuario de etiqueta %s creado: %s (por %s)', area, username, request.user.username)
    return JsonResponse({'ok': True, 'username': username})

@user_passes_test(solo_admin, login_url='login')
@require_POST
def ajax_eliminar_usuario_area(request):
    """Elimina un usuario de etiqueta. Acción irreversible — registrada en el log."""
    user = _get_usuario_etiqueta(request.POST.get('user_id'))
    if not user:
        return JsonResponse({'ok': False, 'error': 'Usuario no válido.'}, status=400)
    nombre = user.username
    user.delete()
    logger.info('Usuario de etiqueta eliminado: %s (por %s)', nombre, request.user.username)
    return JsonResponse({'ok': True, 'username': nombre})

@user_passes_test(solo_admin, login_url='login')
@require_POST
def ajax_editar_usuario_area(request):
    """Edita el correo (obligatorio) de un empleado de etiqueta."""
    user = _get_usuario_etiqueta(request.POST.get('user_id'))
    if not user:
        return JsonResponse({'ok': False, 'error': 'Usuario no válido.'}, status=400)
    try:
        user.email = _limpiar_email(request.POST.get('email'))
    except ValueError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=400)
    user.save(update_fields=['email'])
    return JsonResponse({'ok': True, 'username': user.username, 'email': user.email})


@user_passes_test(solo_admin, login_url='login')
@require_POST
def ajax_resetear_password_area(request):
    """Asigna la nueva clave genérica que escribe el admin a un empleado y vuelve a exigir
    el cambio en el próximo ingreso (`debe_cambiar_password = True`)."""
    user = _get_usuario_etiqueta(request.POST.get('user_id'))
    if not user:
        return JsonResponse({'ok': False, 'error': 'Usuario no válido.'}, status=400)
    try:
        nueva = _limpiar_password_temporal(request.POST.get('password'))
    except ValueError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=400)
    user.set_password(nueva)
    user.save()
    PerfilEmpleado.objects.update_or_create(user=user, defaults={'debe_cambiar_password': True})
    logger.info(
        'Contraseña reseteada (etiqueta): usuario=%s (por %s desde %s)',
        user.username, request.user.username, request.META.get('REMOTE_ADDR'),
    )
    return JsonResponse({'ok': True, 'username': user.username})


# ── Cambio obligatorio en el primer ingreso (empleados de área) ──────────────
# El middleware redirige aquí a los empleados con `debe_cambiar_password=True` y bloquea
# todo lo demás hasta que elijan su clave. Usa SetPasswordForm (no pide la anterior: acaban
# de autenticarse con la genérica) → aplica los AUTH_PASSWORD_VALIDATORS de Django.

@login_required(login_url='login')
def cambiar_password_obligatorio(request):
    perfil = PerfilEmpleado.objects.filter(user=request.user).first()
    # Si ya no debe cambiarla (o no es empleado), no tiene nada que hacer aquí.
    if perfil is None or not perfil.debe_cambiar_password:
        return login_redirect(request)

    if request.method == 'POST':
        form = SetPasswordForm(request.user, request.POST)
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, form.user)  # no cerrar la sesión tras cambiar
            perfil.debe_cambiar_password = False
            perfil.save(update_fields=['debe_cambiar_password'])
            messages.success(request, 'Contraseña actualizada. ¡Bienvenido!')
            return login_redirect(request)
    else:
        form = SetPasswordForm(request.user)

    return render(request, 'usuarios/cambiar_password.html', {'form': form})


# ── "Olvidé mi contraseña" (auto-servicio por correo) ────────────────────────
# Reutiliza las vistas integradas de Django. La única personalización: al confirmar el
# enlace, si quien restablece es un empleado, limpiar `debe_cambiar_password` (acaba de
# elegir su propia clave, ya no debe forzársele el cambio).

class EmpleadoPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    def form_valid(self, form):
        respuesta = super().form_valid(form)
        PerfilEmpleado.objects.filter(user=self.user).update(debe_cambiar_password=False)
        return respuesta


# ── Telemetría: capturador casero de errores del navegador ───────────────────
# Recibe el JSON que arma el capturador de `base_chrome.html` y lo persiste en
# `ErrorCliente`. Disponible en todos los hosts (usuarios/ se incluye en apex y áreas).

_ERR_MAX_BREADCRUMBS = 60
# Topes de los campos JSON: el endpoint es público (RUTAS_PUBLICAS, sin sesión), así que
# sin esto cualquier anónimo podría insertar hasta DATA_UPLOAD_MAX_MEMORY_SIZE (~2.5 MB)
# por request en la BD. Los campos de texto ya se recortan con _recortar.
_ERR_MAX_JSON_BYTES = 8000


def _recortar(valor, limite):
    """Texto seguro y acotado: nunca confiar en el tamaño de lo que manda el navegador."""
    return ('' if valor is None else str(valor))[:limite]


def _acotar_json(valor, vacio):
    """Devuelve `valor` solo si serializado cabe en _ERR_MAX_JSON_BYTES; si no, `vacio`.
    Preferimos descartar a truncar: un JSON truncado a mano quedaría inválido."""
    try:
        if len(json.dumps(valor, ensure_ascii=False)) <= _ERR_MAX_JSON_BYTES:
            return valor
    except (TypeError, ValueError):
        pass
    return vacio


@rate_limit(max_calls=20, periodo=60)
@require_POST
def telemetria_error_cliente(request):
    """
    Persiste un error del navegador. TOLERANTE a propósito: cualquier fallo de parseo o de
    guardado se traga y responde sin 500, para que el propio capturador no genere ruido ni
    bucles (un error al reportar un error no debe romper nada en la página del usuario).
    """
    try:
        payload = json.loads((request.body or b'').decode('utf-8') or '{}')
        if not isinstance(payload, dict):
            return JsonResponse({'ok': False}, status=400)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'ok': False}, status=400)

    breadcrumbs = payload.get('breadcrumbs')
    breadcrumbs = breadcrumbs[-_ERR_MAX_BREADCRUMBS:] if isinstance(breadcrumbs, list) else []
    breadcrumbs = _acotar_json(breadcrumbs, [])
    extra = payload.get('extra') if isinstance(payload.get('extra'), dict) else {}
    extra = _acotar_json(extra, {})

    try:
        ErrorCliente.objects.create(
            usuario     = request.user if request.user.is_authenticated else None,
            area        = _recortar(getattr(request, 'area', '') or payload.get('area'), 30),
            tipo        = _recortar(payload.get('tipo'), 30) or 'desconocido',
            mensaje     = _recortar(payload.get('mensaje'), 2000),
            stack       = _recortar(payload.get('stack'), 8000),
            url         = _recortar(payload.get('url'), 1000),
            user_agent  = _recortar(request.META.get('HTTP_USER_AGENT'), 500),
            breadcrumbs = breadcrumbs,
            extra       = extra,
        )
    except Exception:
        logging.getLogger('aamo').exception('Fallo al registrar ErrorCliente')
        return JsonResponse({'ok': False})

    return JsonResponse({'ok': True})
