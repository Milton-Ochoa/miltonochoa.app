"""Vistas de personalización.

Fase 2 (CRUD de plantillas): lista + subir + eliminar + descargar. Fase 3
(generación): `generar` produce el PDF final rellenando la plantilla con los
estudiantes del Excel. Todas gated con `@solo_logistica` (el middleware ya
bloquea el subdominio; el decorador es la segunda barrera). Las escrituras son
POST-redirect con feedback por `messages` (toasts; logística sí los muestra).
"""
import io
import os

from django.contrib import messages
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .excel import ExcelInvalido, leer_estudiantes
from .forms import GenerarForm, PlantillaForm
from .generar import generar_pdf
from .models import PlantillaPersonalizacion
from .permisos import solo_logistica
from .validaciones import campos_faltantes, validar_plantilla_pdf


@solo_logistica
def lista(request):
    """Plantillas guardadas (ordenadas por tipo/nombre) + form del modal de subida."""
    plantillas = PlantillaPersonalizacion.objects.all()
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
    # Borrar es destructivo (el archivo se pierde del storage) → solo el
    # superusuario. El template oculta el botón; este check es la barrera real.
    if not request.user.is_superuser:
        messages.error(request, 'Solo el administrador puede eliminar plantillas.')
        return redirect('log_personalizacion_lista')
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


@solo_logistica
def generar(request):
    """Rellena la plantilla elegida con los estudiantes del Excel y devuelve el
    PDF resultante. NO persiste nada (los estudiantes no viven en BD). Es un POST
    "de lectura" (produce un archivo, como un export) → permitido en nivel LECTURA.
    """
    if request.method != 'POST':
        return render(request, 'personalizacion/generar.html', {'form': GenerarForm()})

    form = GenerarForm(request.POST, request.FILES)
    if not form.is_valid():
        for errores in form.errors.values():
            for error in errores:
                messages.error(request, error)
        return render(request, 'personalizacion/generar.html', {'form': form})

    plantilla = form.cleaned_data['plantilla']
    colegio = form.cleaned_data['colegio']

    try:
        # El tipo decide las columnas obligatorias (MP añade Código/Año/Estudiante).
        estudiantes = leer_estudiantes(request.FILES['excel'], plantilla.tipo)
    except ExcelInvalido as exc:
        messages.error(request, str(exc))
        return render(request, 'personalizacion/generar.html', {'form': form})

    if not estudiantes:
        messages.error(request, 'El Excel no tiene estudiantes (revisa la columna Nombres).')
        return render(request, 'personalizacion/generar.html', {'form': form})

    contexto = {'colegio': colegio}
    if plantilla.tipo in (PlantillaPersonalizacion.Tipo.PENSAR,
                          PlantillaPersonalizacion.Tipo.MP):
        # nº de prueba (0–99) → decena/unidad. zfill(2): 5 → '05' → decena '0', unidad '5'.
        digitos = str(int(form.cleaned_data['numero_prueba'])).zfill(2)
        contexto['decena'] = digitos[-2]
        contexto['unidad'] = digitos[-1]

    # Bytes de la plantilla (storage-agnóstico: disco en dev, S3/Supabase en prod).
    try:
        plantilla.archivo.open('rb')
        plantilla_bytes = plantilla.archivo.read()
    finally:
        plantilla.archivo.close()

    pdf = generar_pdf(plantilla_bytes=plantilla_bytes, tipo=plantilla.tipo,
                      estudiantes=estudiantes, contexto=contexto)
    nombre = f'{plantilla.tipo.lower()}_{slugify(colegio) or "colegio"}.pdf'
    return FileResponse(io.BytesIO(pdf), as_attachment=True, filename=nombre)
