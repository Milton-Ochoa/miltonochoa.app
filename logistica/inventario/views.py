from django.contrib import messages
from django.db import models
from django.db.models import ProtectedError
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import BodegaForm, CategoriaForm, ItemForm, TerceroForm
from .models import Bodega, Categoria, Item, Stock, Tercero
from .permisos import solo_logistica
from .services import items_bajo_minimo


@solo_logistica
def home(request):
    """Landing del área logística. En la Fase 6 se convierte en el dashboard de
    inventario (tarjetas de stock, préstamos vencidos, últimos movimientos)."""
    return render(request, 'inventario/home.html')


def _form_a_messages(request, form):
    """Vuelca los errores de un form a `messages.error` (los catálogos usan
    modales con POST-redirect, no re-render del form con errores)."""
    for campo, errores in form.errors.items():
        etiqueta = form.fields[campo].label if campo in form.fields else None
        for error in errores:
            messages.error(request, f'{etiqueta}: {error}' if etiqueta else error)


# ---------------------------------------------------------------------------
# Artículos
# ---------------------------------------------------------------------------

@solo_logistica
def items_lista(request):
    items = (Item.objects.select_related('categoria')
             .annotate(stock_total=Coalesce(models.Sum('stocks__cantidad'), 0))
             .order_by('nombre'))
    return render(request, 'inventario/items_lista.html', {
        'items': items,
        'form': ItemForm(),
        'hay_categorias': Categoria.objects.exists(),
        'bajo_minimo_ids': set(items_bajo_minimo().values_list('pk', flat=True)),
    })


@require_POST
@solo_logistica
def item_guardar(request):
    item_id = request.POST.get('item_id') or None
    instancia = get_object_or_404(Item, pk=item_id) if item_id else None
    form = ItemForm(request.POST, instance=instancia)
    if form.is_valid():
        item = form.save()
        verbo = 'actualizado' if instancia else 'creado'
        messages.success(request, f'Artículo "{item.nombre}" {verbo}.')
    else:
        _form_a_messages(request, form)
    return redirect('log_items_lista')


# ---------------------------------------------------------------------------
# Catálogos: bodegas, categorías, terceros
# ---------------------------------------------------------------------------

@solo_logistica
def bodegas(request):
    if request.method == 'POST':
        if request.POST.get('accion') == 'toggle':
            bodega = get_object_or_404(Bodega, pk=request.POST.get('bodega_id'))
            if bodega.activa:
                # Guard del soft-delete: una bodega con existencias no se puede
                # desactivar (quedaría stock "invisible" para los documentos).
                total = bodega.stocks.aggregate(t=models.Sum('cantidad'))['t'] or 0
                if total > 0:
                    messages.error(
                        request,
                        f'No se puede desactivar "{bodega.nombre}": aún tiene '
                        f'{total} unidades en existencia. Trasládalas o ajústalas primero.')
                    return redirect('log_bodegas')
                bodega.activa = False
                messages.success(request, f'Bodega "{bodega.nombre}" desactivada.')
            else:
                bodega.activa = True
                messages.success(request, f'Bodega "{bodega.nombre}" reactivada.')
            bodega.save(update_fields=['activa'])
        else:
            bodega_id = request.POST.get('bodega_id') or None
            instancia = get_object_or_404(Bodega, pk=bodega_id) if bodega_id else None
            form = BodegaForm(request.POST, instance=instancia)
            if form.is_valid():
                bodega = form.save()
                verbo = 'actualizada' if instancia else 'creada'
                messages.success(request, f'Bodega "{bodega.nombre}" {verbo}.')
            else:
                _form_a_messages(request, form)
        return redirect('log_bodegas')

    lista = (Bodega.objects
             .annotate(stock_total=Coalesce(models.Sum('stocks__cantidad'), 0))
             .order_by('nombre'))
    return render(request, 'inventario/bodegas.html', {'bodegas': lista})


@solo_logistica
def categorias(request):
    if request.method == 'POST':
        if request.POST.get('accion') == 'eliminar':
            categoria = get_object_or_404(Categoria, pk=request.POST.get('categoria_id'))
            try:
                categoria.delete()
                messages.success(request, f'Categoría "{categoria.nombre}" eliminada.')
            except ProtectedError:
                messages.error(
                    request,
                    f'No se puede eliminar "{categoria.nombre}": hay artículos '
                    f'en esa categoría.')
        else:
            categoria_id = request.POST.get('categoria_id') or None
            instancia = (get_object_or_404(Categoria, pk=categoria_id)
                         if categoria_id else None)
            form = CategoriaForm(request.POST, instance=instancia)
            if form.is_valid():
                categoria = form.save()
                verbo = 'actualizada' if instancia else 'creada'
                messages.success(request, f'Categoría "{categoria.nombre}" {verbo}.')
            else:
                _form_a_messages(request, form)
        return redirect('log_categorias')

    lista = Categoria.objects.annotate(n_items=models.Count('items')).order_by('nombre')
    return render(request, 'inventario/categorias.html', {'categorias': lista})


@solo_logistica
def terceros(request):
    if request.method == 'POST':
        if request.POST.get('accion') == 'toggle':
            tercero = get_object_or_404(Tercero, pk=request.POST.get('tercero_id'))
            tercero.activo = not tercero.activo
            tercero.save(update_fields=['activo'])
            verbo = 'reactivado' if tercero.activo else 'desactivado'
            messages.success(request, f'Tercero "{tercero.nombre}" {verbo}.')
        else:
            tercero_id = request.POST.get('tercero_id') or None
            instancia = (get_object_or_404(Tercero, pk=tercero_id)
                         if tercero_id else None)
            form = TerceroForm(request.POST, instance=instancia)
            if form.is_valid():
                tercero = form.save()
                verbo = 'actualizado' if instancia else 'creado'
                messages.success(request, f'Tercero "{tercero.nombre}" {verbo}.')
            else:
                _form_a_messages(request, form)
        return redirect('log_terceros')

    return render(request, 'inventario/terceros.html',
                  {'terceros': Tercero.objects.order_by('nombre')})


@require_POST
@solo_logistica
def tercero_ajax_crear(request):
    """Alta de tercero al vuelo (JSON). Lo consumen los forms de salidas (F4)
    y préstamos (F5) para no abandonar el documento a medio llenar.

    Contrato: éxito → {ok: true, tercero: {id, nombre, documento, label}};
    error → 400 + {ok: false, error: '<texto legible>'}.
    """
    form = TerceroForm(request.POST)
    if form.is_valid():
        tercero = form.save()
        return JsonResponse({'ok': True, 'tercero': {
            'id': tercero.pk,
            'nombre': tercero.nombre,
            'documento': tercero.documento,
            'label': str(tercero),
        }})
    error = '; '.join(e for lista in form.errors.values() for e in lista)
    return JsonResponse({'ok': False, 'error': error}, status=400)


# ---------------------------------------------------------------------------
# Existencias
# ---------------------------------------------------------------------------

@solo_logistica
def stock(request):
    """Existencias por item×bodega (el denormalizado que mantienen los
    servicios). Las filas en 0 se muestran a propósito: dicen "este item vivió
    en esta bodega" y son el punto de entrada del ajuste (modal en F4)."""
    filas = (Stock.objects
             .select_related('item', 'item__categoria', 'bodega')
             .filter(item__activo=True)
             .order_by('item__nombre', 'bodega__nombre'))
    alertas = list(items_bajo_minimo())
    return render(request, 'inventario/stock.html', {
        'filas': filas,
        'items_alerta': alertas,
        'bajo_minimo_ids': {item.pk for item in alertas},
    })
