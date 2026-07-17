"""Vistas de despachos.

F2: solo la carga del reporte diario. El tablero, el detalle y las acciones de
estado/cambio de material llegan en F3/F4. Gate `@solo_logistica` (el middleware
ya bloquea el subdominio; el decorador es la segunda barrera). La carga es un
POST-redirect con feedback por `messages` (logística sí muestra toasts).
"""
from django.contrib import messages
from django.shortcuts import redirect, render

from .forms import CargaReporteForm
from .models import CargaReporte
from .permisos import solo_logistica
from .reporte import ReporteInvalido
from .services import ReporteViejo, importar_reporte


@solo_logistica
def cargar(request):
    """GET: form de subida + historial de cargas (bitácora + 'datos al día de…').
    POST: parsea e importa el reporte; traduce los errores de dominio a toasts."""
    if request.method == 'POST':
        form = CargaReporteForm(request.POST, request.FILES)
        if not form.is_valid():
            for errores in form.errors.values():
                for error in errores:
                    messages.error(request, error)
            return redirect('log_despachos_cargar')

        archivo = form.cleaned_data['archivo']
        try:
            carga = importar_reporte(archivo=archivo, nombre_archivo=archivo.name,
                                     usuario=request.user)
        except (ReporteInvalido, ReporteViejo) as exc:
            messages.error(request, str(exc))
            return redirect('log_despachos_cargar')

        messages.success(
            request,
            f'Reporte importado: {carga.n_ordenes} órdenes '
            f'({carga.n_nuevas} nuevas, {carga.n_actualizadas} actualizadas, '
            f'{carga.n_cerradas_auto} cerradas, {carga.n_alertas_remision} alertas).')
        return redirect('log_despachos_cargar')

    cargas = CargaReporte.objects.select_related('usuario')[:30]
    return render(request, 'despachos/cargar.html', {
        'form': CargaReporteForm(),
        'cargas': cargas,
        'ultima': cargas[0] if cargas else None,
    })
