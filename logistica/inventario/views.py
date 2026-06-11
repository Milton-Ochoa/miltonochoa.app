from django.shortcuts import render

from .permisos import solo_logistica


@solo_logistica
def home(request):
    """Landing del área logística. En la Fase 6 se convierte en el dashboard de
    inventario (tarjetas de stock, préstamos vencidos, últimos movimientos)."""
    return render(request, 'inventario/home.html')
