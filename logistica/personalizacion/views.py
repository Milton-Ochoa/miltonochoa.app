"""Vistas de personalización.

Fase 2 (CRUD de plantillas): lista + subir + eliminar + descargar. La
generación del PDF (Fase 3) se añade después. Todas gated con `@solo_logistica`
(el middleware ya bloquea el subdominio; el decorador es la segunda barrera).
Las escrituras son POST-redirect con feedback por `messages` (toasts; logística
sí los muestra).
"""
import os

from django.contrib import messages
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import PlantillaForm
from .models import PlantillaPersonalizacion
from .permisos import solo_logistica
from .validaciones import campos_faltantes, validar_plantilla_pdf


@solo_logistica
def lista(request):
    """Plantillas guardadas (ordenadas por tipo/nombre) + form del modal de subida."""
    plantillas = PlantillaPersonalizacion.objects.select_related('subido_por')
    return render(request, 'personalizacion/lista.html', {
        'plantillas': plantillas,
        'form': PlantillaForm(),
    })


@require_POST
@solo_logistica
def plantilla_subir(request):
    form = PlantillaForm(request.POST, request.FILES)
    if not form.is_valid():
        for errores in form.errors.values():
            for error in errores:
                messages.error(request, error)
        return redirect('log_personalizacion_lista')

    archivo = form.cleaned_data['archivo']
    error = validar_plantilla_pdf(archivo)  # validación DURA: bloquea la subida
    if error:
        messages.error(request, error)
        return redirect('log_personalizacion_lista')

    plantilla = form.save(commit=False)
    plantilla.subido_por = request.user
    plantilla.save()

    # Aviso SUAVE: si la plantilla no trae todos los campos que el tipo espera
    # rellenar, se avisa sin bloquear (leyendo los bytes sin consumir el stream
    # que ya guardó el storage).
    try:
        plantilla.archivo.open('rb')
        contenido = plantilla.archivo.read()
    finally:
        plantilla.archivo.close()
    faltantes = campos_faltantes(contenido, plantilla.tipo)
    if faltantes:
        messages.warning(
            request,
            'La plantilla se guardó, pero le faltan campos que este tipo '
            'espera rellenar: ' + ', '.join(faltantes) + '.')

    messages.success(request, f'Plantilla «{plantilla.nombre}» guardada.')
    return redirect('log_personalizacion_lista')


@require_POST
@solo_logistica
def plantilla_eliminar(request, pk):
    plantilla = get_object_or_404(PlantillaPersonalizacion, pk=pk)
    nombre = plantilla.nombre
    # Primero el archivo del storage, luego la fila (patrón adjuntos de entrada).
    plantilla.archivo.delete(save=False)
    plantilla.delete()
    messages.success(request, f'Plantilla «{nombre}» eliminada.')
    return redirect('log_personalizacion_lista')


@solo_logistica
def plantilla_descargar(request, pk):
    """Descarga proxiada por el backend de storage (disco o S3): el gate de
    permiso queda server-side y NUNCA se exponen URLs firmadas. `?inline=1`
    abre en pestaña; por defecto descarga."""
    plantilla = get_object_or_404(PlantillaPersonalizacion, pk=pk)
    nombre = os.path.basename(plantilla.archivo.name)
    return FileResponse(plantilla.archivo.open('rb'),
                        as_attachment=request.GET.get('inline') != '1',
                        filename=nombre)
