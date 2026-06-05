from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import HttpResponseForbidden, HttpResponse
from django.utils import timezone
from datetime import timedelta
from .models import Tarea
from django.db.models import Q


ESTADOS_VALIDOS = {'pendiente', 'gestion', 'completado'}


@login_required
def kanban_inicio(request):
    """
    Vista principal del tablero Kanban (home '/').

    Carga las tareas pendientes, en gestión y completadas (solo las completadas
    en los últimos 2 días — las más antiguas se ocultan para no saturar la UI).
    También maneja el POST de creación de nueva tarea desde el mismo home.
    Si la petición lleva HX-Request (HTMX), retorna solo el card HTML de la
    nueva tarea para que el JS la prepend a la columna correspondiente.
    """
    hace_dos_dias = timezone.now() - timedelta(days=2)
    tareas = list(Tarea.objects.filter(
        Q(estado__in=['pendiente', 'gestion']) |
        Q(estado='completado', fecha_completado__gte=hace_dos_dias)
    ).order_by('-fecha_completado'))

    if request.method == 'POST' and 'crear_tarea' in request.POST:
        titulo = request.POST.get('titulo', '').strip()
        nueva = None
        if titulo:
            nueva = Tarea.objects.create(titulo=titulo, creado_por=request.user)
        if bool(request.META.get('HTTP_HX_REQUEST')) and nueva:
            return render(request, 'pendientes/_partials/_card_tarea.html',
                          {'tarea': nueva, 'user': request.user})
        return redirect('home')

    return render(request, 'home.html', {
        'pendientes': [t for t in tareas if t.estado == 'pendiente'],
        'en_gestion': [t for t in tareas if t.estado == 'gestion'],
        'completados': [t for t in tareas if t.estado == 'completado'],
    })


@login_required
@require_POST
def cambiar_estado(request, tarea_id, nuevo_estado):
    """
    Mueve una tarea entre columnas del Kanban.
    Puede cambiarla el creador o cualquier personal de programación (superusuario
    o staff de área): el Kanban es un tablero de equipo del área.
    Al marcar 'completado' registra quién completó la tarea; al salir de ese estado
    limpia `completado_por` para no dejar datos huérfanos.
    Si la petición lleva HX-Request retorna el card HTML de la tarea en su nuevo
    estado (para que el JS la inserte en la columna destino).
    """
    tarea = get_object_or_404(Tarea, id=tarea_id)
    if not request.es_personal_programacion and tarea.creado_por != request.user:
        return HttpResponseForbidden()

    if nuevo_estado in ESTADOS_VALIDOS:
        tarea.estado = nuevo_estado
        tarea.completado_por = request.user if nuevo_estado == 'completado' else None
        tarea.save()

    if bool(request.META.get('HTTP_HX_REQUEST')):
        return render(request, 'pendientes/_partials/_card_tarea.html',
                      {'tarea': tarea, 'user': request.user})
    return redirect('home')


@login_required
@require_POST
def editar_tarea(request, tarea_id):
    """
    Actualiza la descripción de una tarea (edición inline desde el Kanban).
    Trunca a 2000 chars para prevenir payloads gigantes; el modelo no tiene
    max_length definido en BD, así que la validación es exclusivamente aquí.
    Si la petición lleva HX-Request retorna el card HTML actualizado (OOB swap).
    """
    tarea = get_object_or_404(Tarea, id=tarea_id)
    if not request.es_personal_programacion and tarea.creado_por != request.user:
        return HttpResponseForbidden()

    descripcion = request.POST.get('descripcion', '')
    tarea.descripcion = descripcion[:2000]  # limite razonable
    tarea.save()

    if bool(request.META.get('HTTP_HX_REQUEST')):
        return render(request, 'pendientes/_partials/_card_tarea.html',
                      {'tarea': tarea, 'user': request.user})
    return redirect('home')