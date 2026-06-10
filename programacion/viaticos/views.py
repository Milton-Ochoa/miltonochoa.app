"""Vistas del área **programación** para solicitudes de viáticos.

Aquí el staff de programación crea, lista, edita (mientras la solicitud sigue
`ENVIADA`/`DEVUELTA`) y reenvía solicitudes. La gestión por parte de financiera
(devolver/aprobar/pagar) vive en la app `financiera.viaticos`.
"""
import os
import re

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.db import transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.areas import es_personal_programacion
from programacion.configuracion.models import Colegio, Profesor
from .forms import SolicitudViaticoForm
from .models import GastoViatico, SolicitudViatico, SoportePago
from .notificaciones import notificar_legalizacion_enviada, notificar_solicitud_enviada
from .soportes import validar_soporte

# Superusuario o staff del área (grupo area:programacion). Mismo predicado que
# el resto del área; los gestores de colegio/profesor NO pasan → no ven viáticos.
solo_personal = user_passes_test(es_personal_programacion, login_url='login')

# Estados en los que programación todavía puede editar/reenviar la solicitud.
# APROBADA y PAGADA son de solo lectura para programación (las gestiona financiera).
EDITABLES_PROGRAMACION = {SolicitudViatico.Estado.ENVIADA, SolicitudViatico.Estado.DEVUELTA}

# Estados en los que programación gestiona la legalización (subir/borrar soportes y
# enviarla a financiera): tras el pago, o cuando financiera la devolvió a corregir.
LEGALIZABLES = {SolicitudViatico.Estado.PAGADA, SolicitudViatico.Estado.LEG_DEVUELTA}


def _parsear_gastos(request):
    """Extrae las filas de gasto del POST y las valida.

    Devuelve `(gastos, errores)` donde `gastos` es una lista de dicts
    ``{'nombre', 'valor', 'orden'}`` lista para crear `GastoViatico`. El total
    NO se lee del POST: se recalcula desde estos valores (propiedad `total`).
    """
    nombres = request.POST.getlist('gasto_nombre')
    valores = request.POST.getlist('gasto_valor')

    gastos, errores = [], []
    for nombre, valor_raw in zip(nombres, valores):
        nombre = nombre.strip()
        # Solo dígitos: el front puede escribir el valor con separadores de miles.
        valor_digits = re.sub(r'[^\d]', '', valor_raw or '')
        if not nombre and not valor_digits:
            continue  # fila vacía → se ignora (el form arranca con 1 fila en blanco)
        if not nombre:
            errores.append('Hay un gasto sin nombre.')
            continue
        if not valor_digits or int(valor_digits) <= 0:
            errores.append(f'El gasto «{nombre}» necesita un valor mayor a 0.')
            continue
        gastos.append({'nombre': nombre, 'valor': int(valor_digits), 'orden': len(gastos)})

    if not gastos and not errores:
        errores.append('Agrega al menos un gasto con valor mayor a 0.')
    return gastos, errores


def _contexto_form(form, gastos=None):
    """Contexto común de crear/editar: form + catálogos para los selects con
    autorrelleno (data-*) + gastos a pintar (lista de dicts o de GastoViatico)."""
    return {
        'form': form,
        'profesores': Profesor.objects.order_by('nombre', 'apellido'),
        'colegios': Colegio.objects.order_by('nombre'),
        'gastos': gastos or [],
    }


@solo_personal
def lista_viaticos(request):
    """Tabla de todas las solicitudes (solo las ve el staff, así que no se filtra
    por usuario). Muestra estado y total."""
    solicitudes = (
        SolicitudViatico.objects
        .select_related('profesor', 'colegio')
        .prefetch_related('gastos')
    )
    return render(request, 'viaticos/lista.html', {'solicitudes': solicitudes})


@solo_personal
def crear_viatico(request):
    """GET: formulario vacío (1 fila de gasto). POST: valida, copia el snapshot
    desde las FK y crea la solicitud (`ENVIADA`) con sus gastos."""
    if request.method == 'POST':
        form = SolicitudViaticoForm(request.POST)
        gastos, errores_gastos = _parsear_gastos(request)
        for e in errores_gastos:
            messages.error(request, e)

        if form.is_valid() and not errores_gastos:
            with transaction.atomic():
                solicitud = form.save(commit=False)
                solicitud.creado_por = request.user
                solicitud.estado = SolicitudViatico.Estado.ENVIADA
                solicitud.aplicar_snapshot()  # el servidor recalcula desde la FK
                solicitud.save()
                GastoViatico.objects.bulk_create(
                    GastoViatico(solicitud=solicitud, **g) for g in gastos
                )
                # Avisar a financiera solo si la transacción se confirma (no en rollback).
                transaction.on_commit(lambda: notificar_solicitud_enviada(solicitud, request))
            messages.success(request, 'Solicitud de viáticos enviada.')
            return redirect('viaticos_detalle', pk=solicitud.pk)

        # Reusar lo enviado (gastos parseados) para no perder lo escrito.
        return render(request, 'viaticos/form.html', _contexto_form(form, gastos))

    return render(request, 'viaticos/form.html', _contexto_form(SolicitudViaticoForm()))


@solo_personal
def editar_viatico(request, pk):
    """Reedita una solicitud `ENVIADA`/`DEVUELTA`. Si venía `DEVUELTA` y se pulsa
    «Reenviar», vuelve a `ENVIADA` y limpia el motivo de devolución."""
    solicitud = get_object_or_404(SolicitudViatico, pk=pk)
    if solicitud.estado not in EDITABLES_PROGRAMACION:
        messages.error(request, 'Esta solicitud ya no se puede editar desde programación.')
        return redirect('viaticos_detalle', pk=solicitud.pk)

    if request.method == 'POST':
        form = SolicitudViaticoForm(request.POST, instance=solicitud)
        gastos, errores_gastos = _parsear_gastos(request)
        for e in errores_gastos:
            messages.error(request, e)

        if form.is_valid() and not errores_gastos:
            reenviar = 'reenviar' in request.POST and solicitud.estado == SolicitudViatico.Estado.DEVUELTA
            with transaction.atomic():
                solicitud = form.save(commit=False)
                solicitud.aplicar_snapshot()
                if reenviar:
                    solicitud.estado = SolicitudViatico.Estado.ENVIADA
                    solicitud.motivo_devolucion = ''
                solicitud.save()
                # Reemplazo total de gastos: más simple y seguro que diff por fila.
                solicitud.gastos.all().delete()
                GastoViatico.objects.bulk_create(
                    GastoViatico(solicitud=solicitud, **g) for g in gastos
                )
                # Solo el reenvío (DEVUELTA→ENVIADA) vuelve a requerir revisión; una
                # edición que no cambia de estado no debe notificar.
                if reenviar:
                    transaction.on_commit(lambda: notificar_solicitud_enviada(solicitud, request))
            messages.success(request, 'Solicitud reenviada.' if reenviar else 'Solicitud actualizada.')
            return redirect('viaticos_detalle', pk=solicitud.pk)

        return render(request, 'viaticos/form.html',
                      {**_contexto_form(form, gastos), 'solicitud': solicitud})

    form = SolicitudViaticoForm(instance=solicitud)
    return render(request, 'viaticos/form.html',
                  {**_contexto_form(form, list(solicitud.gastos.all())), 'solicitud': solicitud})


@solo_personal
def detalle_viatico(request, pk):
    """Vista de solo lectura: estado, motivo de devolución (si lo hay), gastos y total."""
    solicitud = get_object_or_404(
        SolicitudViatico.objects.select_related('profesor', 'colegio')
        .prefetch_related('gastos', 'soportes', 'soportes__subido_por'),
        pk=pk,
    )
    return render(request, 'viaticos/detalle.html', {
        'solicitud': solicitud,
        'puede_editar': solicitud.estado in EDITABLES_PROGRAMACION,
        'puede_legalizar': solicitud.estado in LEGALIZABLES,
    })


def _responder_soporte(soporte, *, inline):
    """Transmite el archivo del soporte vía el backend de storage (disco o S3).

    Proxiar por Django (en vez de exponer URLs firmadas) deja el gate de
    permiso en cada vista server-side y funciona idéntico en dev y prod. El
    nombre de descarga es el nombre limpio que ya fijó `_soporte_upload_to`.
    """
    nombre = os.path.basename(soporte.archivo.name)
    return FileResponse(soporte.archivo.open('rb'), as_attachment=not inline, filename=nombre)


@solo_personal
def soporte_descargar(request, soporte_id):
    """Ver (``?inline=1``) o descargar el soporte de pago de un viático."""
    soporte = get_object_or_404(SoportePago, pk=soporte_id)
    return _responder_soporte(soporte, inline=request.GET.get('inline') == '1')


# ══════════════════════════════════════════════════════════════
# LEGALIZACIÓN (post-pago: programación rinde cuentas a financiera)
# ══════════════════════════════════════════════════════════════

@solo_personal
@require_POST
def legalizacion_subir_soporte(request, pk):
    """Adjunta un soporte de legalización (solo en `PAGADA`/`LEG_DEVUELTA`)."""
    solicitud = get_object_or_404(SolicitudViatico, pk=pk)
    if solicitud.estado not in LEGALIZABLES:
        messages.error(request, 'La legalización no se puede modificar en el estado actual.')
        return redirect('viaticos_detalle', pk=solicitud.pk)

    archivo = request.FILES.get('archivo')
    if not archivo:
        messages.error(request, 'Selecciona un archivo para subir.')
        return redirect('viaticos_detalle', pk=solicitud.pk)

    error = validar_soporte(archivo)
    if error:
        messages.error(request, error)
        return redirect('viaticos_detalle', pk=solicitud.pk)

    SoportePago.objects.create(
        solicitud=solicitud,
        tipo=SoportePago.Tipo.LEGALIZACION,
        archivo=archivo,
        nombre_original=archivo.name,
        subido_por=request.user,
    )
    messages.success(request, 'Soporte de legalización adjuntado.')
    return redirect('viaticos_detalle', pk=solicitud.pk)


@solo_personal
@require_POST
def legalizacion_eliminar_soporte(request, soporte_id):
    """Elimina un soporte de legalización (solo ese tipo: los de pago son de
    financiera) mientras la legalización siga en manos de programación."""
    soporte = get_object_or_404(
        SoportePago.objects.select_related('solicitud'),
        pk=soporte_id, tipo=SoportePago.Tipo.LEGALIZACION,
    )
    pk = soporte.solicitud_id
    if soporte.solicitud.estado not in LEGALIZABLES:
        messages.error(request, 'La legalización no se puede modificar en el estado actual.')
        return redirect('viaticos_detalle', pk=pk)
    # Borrar primero el archivo del storage (S3/disco), luego la fila.
    soporte.archivo.delete(save=False)
    soporte.delete()
    messages.success(request, 'Soporte de legalización eliminado.')
    return redirect('viaticos_detalle', pk=pk)


@solo_personal
@require_POST
def legalizacion_enviar(request, pk):
    """`PAGADA`/`LEG_DEVUELTA` → `LEG_ENVIADA`. Exige ≥1 soporte de legalización
    (sin documentos no hay nada que revisar) y avisa por correo a financiera."""
    solicitud = get_object_or_404(SolicitudViatico, pk=pk)
    if solicitud.estado not in LEGALIZABLES:
        messages.error(request, 'Solo se puede enviar la legalización de una solicitud pagada o devuelta.')
        return redirect('viaticos_detalle', pk=solicitud.pk)
    if not solicitud.soportes_legalizacion:
        messages.error(request, 'Adjunta al menos un soporte de legalización antes de enviar.')
        return redirect('viaticos_detalle', pk=solicitud.pk)

    with transaction.atomic():
        solicitud.estado = SolicitudViatico.Estado.LEG_ENVIADA
        solicitud.legalizacion_enviada_en = timezone.now()
        solicitud.motivo_devolucion = ''  # mismo ciclo que ENVIADA↔DEVUELTA: reenviar limpia el motivo
        solicitud.save()
        transaction.on_commit(lambda: notificar_legalizacion_enviada(solicitud, request))
    messages.success(request, 'Legalización enviada a financiera.')
    return redirect('viaticos_detalle', pk=solicitud.pk)
