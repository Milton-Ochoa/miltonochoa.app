from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User, Group
from django.contrib.auth.decorators import user_passes_test, login_required
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST
import secrets
import logging

from .models import UsuarioColegio, UsuarioProfesor
from .ratelimit import rate_limit
from programacion.configuracion.models import Colegio, Profesor
from core.areas import AREAS, url_apex, url_en_area, host_apex, host_de_area, GRUPO_STAFF_PROGRAMACION, es_personal_programacion

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

def _generar_password():
    # 9 bytes → 12 chars base64url; entropía suficiente para una credencial temporal.
    return secrets.token_urlsafe(9)

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

@rate_limit(max_calls=10, periodo=60)
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
    Crea un usuario de colegio o profesor y devuelve la contraseña temporal en texto plano.
    Esta es la única vez que la contraseña es visible — el frontend debe mostrarla al admin
    y no hay forma de recuperarla después.
    """
    tipo = request.POST.get('tipo')
    username = request.POST.get('username', '').strip()

    if not username or tipo not in ('colegio', 'profesor'):
        return JsonResponse({'ok': False, 'error': 'Datos inválidos.'}, status=400)

    password = _generar_password()

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
        'password_inicial': password,
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
    Genera y asigna una nueva contraseña temporal. Se devuelve en texto plano una sola vez.
    Operación auditada: registra quién reseteó, a quién, y desde qué IP.
    """
    tipo      = request.POST.get('tipo')
    perfil_id = request.POST.get('perfil_id')

    if tipo not in ('colegio', 'profesor') or not perfil_id:
        return JsonResponse({'ok': False, 'error': 'Datos inválidos.'}, status=400)

    modelo = UsuarioColegio if tipo == 'colegio' else UsuarioProfesor
    perfil = get_object_or_404(modelo, id=perfil_id)

    nueva = _generar_password()
    perfil.user.set_password(nueva)
    perfil.user.save()

    logger.info(
        'Contraseña reseteada: perfil %s id=%s usuario=%s (por %s desde %s)',
        tipo, perfil_id, perfil.user.username,
        request.user.username, request.META.get('REMOTE_ADDR'),
    )
    return JsonResponse({'ok': True, 'nueva_password': nueva, 'username': perfil.user.username})


# ── Usuarios de etiqueta (grupo 'area:programacion') ─────────────────────────
# A diferencia de colegio/profesor, no tienen perfil: son usuarios genéricos del área
# (acceso completo de staff, ver core.areas.es_personal_programacion). Se gestionan
# desde el panel del superusuario en el apex.

def _get_usuario_etiqueta(user_id):
    """User del grupo etiqueta y NO superusuario; None si no aplica (evita tocar admins)."""
    if not user_id:
        return None
    return (User.objects
            .filter(id=user_id, groups__name=GRUPO_STAFF_PROGRAMACION, is_superuser=False)
            .first())

@user_passes_test(solo_admin, login_url='login')
@require_POST
def ajax_crear_usuario_area(request):
    """
    Crea un usuario de etiqueta 'programacion' y devuelve su contraseña temporal una vez.

    El usuario no es is_staff (no entra a /admin/) ni superusuario; pertenecer al grupo
    'area:programacion' basta para que el login lo lleve al subdominio del área y el
    middleware le conceda acceso completo dentro de ella.
    """
    username = request.POST.get('username', '').strip()
    if not username:
        return JsonResponse({'ok': False, 'error': 'El nombre de usuario es obligatorio.'}, status=400)
    if User.objects.filter(username=username).exists():
        return JsonResponse({'ok': False, 'error': f'El usuario "{username}" ya existe.'}, status=400)

    password = _generar_password()
    try:
        with transaction.atomic():
            user = User.objects.create_user(
                username=username, password=password,
                is_staff=False, is_superuser=False,
            )
            grupo, _ = Group.objects.get_or_create(name=GRUPO_STAFF_PROGRAMACION)
            user.groups.add(grupo)
    except Exception:
        logger.exception('Error al crear usuario de etiqueta')
        return JsonResponse({'ok': False, 'error': 'Error interno. Intenta de nuevo.'}, status=500)

    logger.info('Usuario de etiqueta programacion creado: %s (por %s)', username, request.user.username)
    return JsonResponse({'ok': True, 'username': username, 'password_inicial': password})

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
def ajax_resetear_password_area(request):
    """Genera y asigna una nueva contraseña temporal a un usuario de etiqueta (una vez)."""
    user = _get_usuario_etiqueta(request.POST.get('user_id'))
    if not user:
        return JsonResponse({'ok': False, 'error': 'Usuario no válido.'}, status=400)
    nueva = _generar_password()
    user.set_password(nueva)
    user.save()
    logger.info(
        'Contraseña reseteada (etiqueta): usuario=%s (por %s desde %s)',
        user.username, request.user.username, request.META.get('REMOTE_ADDR'),
    )
    return JsonResponse({'ok': True, 'nueva_password': nueva, 'username': user.username})
