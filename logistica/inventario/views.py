import os
from datetime import date

from django.contrib import messages
from django.db import models
from django.db.models import ProtectedError
from django.db.models.functions import Coalesce
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .adjuntos import validar_adjunto
from .forms import (BodegaForm, CategoriaForm, EntradaForm, ItemForm,
                    PrestamoForm, SalidaForm, TerceroForm, TrasladoForm,
                    parsear_lineas)
from .models import (AdjuntoEntrada, Bodega, Categoria, Entrada, Item,
                     Movimiento, Prestamo, Salida, Stock, Tercero, Traslado)
from .permisos import solo_logistica
from .services import (ErrorDevolucion, StockInsuficiente, crear_prestamo,
                       items_bajo_minimo, kardex, registrar_ajuste,
                       registrar_devolucion, registrar_entrada,
                       registrar_salida, registrar_traslado)


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


# ---------------------------------------------------------------------------
# Documentos: entradas, salidas, traslados (Fase 4)
#
# Patrón común: la cabecera la valida un form, las líneas las parsea
# `parsear_lineas` y el documento lo crea SIEMPRE el servicio de dominio
# (atómico: si una línea falla, nada queda escrito). En error se re-renderiza
# el form con las líneas que traía el POST (`lineas_previas`) para no perder
# lo digitado; en éxito, POST-redirect al detalle con toast.
# ---------------------------------------------------------------------------

def _lineas_previas(post, *, con_bodega=False):
    """Las líneas crudas del POST, para repintar `_lineas_doc.html` tras un error."""
    items = post.getlist('linea_item')
    cantidades = post.getlist('linea_cantidad')
    bodegas = post.getlist('linea_bodega') if con_bodega else [''] * len(items)
    return [{'item_id': i, 'cantidad': c, 'bodega_id': b}
            for i, c, b in zip(items, cantidades, bodegas)]


def _items_para_lineas():
    return Item.objects.filter(activo=True).order_by('nombre')


@solo_logistica
def entradas_lista(request):
    lista = (Entrada.objects.select_related('bodega', 'creado_por')
             .annotate(n_lineas=models.Count('lineas', distinct=True),
                       unidades=Coalesce(models.Sum('lineas__cantidad'), 0))
             .order_by('-creado_en'))
    return render(request, 'inventario/entradas_lista.html', {'entradas': lista})


@solo_logistica
def entrada_nueva(request):
    form = EntradaForm(request.POST or None)
    if request.method == 'POST':
        try:
            if not form.is_valid():
                _form_a_messages(request, form)
                raise ValueError('')  # cae al re-render conservando las líneas
            lineas = parsear_lineas(request.POST)
            entrada = registrar_entrada(
                bodega=form.cleaned_data['bodega'], lineas=lineas,
                usuario=request.user,
                proveedor=form.cleaned_data['proveedor'],
                observaciones=form.cleaned_data['observaciones'])
        except ValueError as e:
            if str(e):
                messages.error(request, str(e))
        else:
            messages.success(request, f'Entrada #{entrada.pk} registrada.')
            return redirect('log_entradas_detalle', pk=entrada.pk)
    return render(request, 'inventario/entrada_form.html', {
        'form': form,
        'items': _items_para_lineas(),
        'lineas_previas': _lineas_previas(request.POST) if request.method == 'POST' else [],
    })


@solo_logistica
def entrada_detalle(request, pk):
    entrada = get_object_or_404(
        Entrada.objects.select_related('bodega', 'creado_por')
        .prefetch_related('lineas__item', 'adjuntos__subido_por'), pk=pk)
    return render(request, 'inventario/entrada_detalle.html', {'entrada': entrada})


@require_POST
@solo_logistica
def entrada_adjunto_subir(request, pk):
    entrada = get_object_or_404(Entrada, pk=pk)
    archivo = request.FILES.get('archivo')
    if not archivo:
        messages.error(request, 'Selecciona un archivo para subir.')
        return redirect('log_entradas_detalle', pk=entrada.pk)
    error = validar_adjunto(archivo)
    if error:
        messages.error(request, error)
        return redirect('log_entradas_detalle', pk=entrada.pk)
    AdjuntoEntrada.objects.create(
        entrada=entrada, archivo=archivo,
        nombre_original=archivo.name[:255], subido_por=request.user)
    messages.success(request, 'Adjunto subido.')
    return redirect('log_entradas_detalle', pk=entrada.pk)


@require_POST
@solo_logistica
def entrada_adjunto_eliminar(request, adjunto_id):
    adjunto = get_object_or_404(AdjuntoEntrada, pk=adjunto_id)
    entrada_pk = adjunto.entrada_id
    # Primero el archivo del storage, luego la fila (patrón soportes de pago).
    adjunto.archivo.delete(save=False)
    adjunto.delete()
    messages.success(request, 'Adjunto eliminado.')
    return redirect('log_entradas_detalle', pk=entrada_pk)


@solo_logistica
def entrada_adjunto_descargar(request, adjunto_id):
    """Descarga proxiada por el backend de storage (disco o S3): el gate de
    permiso queda server-side y NUNCA se exponen URLs firmadas. `?inline=1`
    abre en pestaña; por defecto descarga."""
    adjunto = get_object_or_404(AdjuntoEntrada, pk=adjunto_id)
    nombre = os.path.basename(adjunto.archivo.name)
    return FileResponse(adjunto.archivo.open('rb'),
                        as_attachment=request.GET.get('inline') != '1',
                        filename=nombre)


@solo_logistica
def salidas_lista(request):
    lista = (Salida.objects.select_related('bodega', 'creado_por')
             .annotate(n_lineas=models.Count('lineas', distinct=True),
                       unidades=Coalesce(models.Sum('lineas__cantidad'), 0))
             .order_by('-creado_en'))
    return render(request, 'inventario/salidas_lista.html', {'salidas': lista})


@solo_logistica
def salida_nueva(request):
    form = SalidaForm(request.POST or None)
    if request.method == 'POST':
        try:
            if not form.is_valid():
                _form_a_messages(request, form)
                raise ValueError('')
            lineas = parsear_lineas(request.POST)
            salida = registrar_salida(
                bodega=form.cleaned_data['bodega'], lineas=lineas,
                usuario=request.user,
                tercero=form.cleaned_data['tercero'],
                motivo=form.cleaned_data['motivo'],
                observaciones=form.cleaned_data['observaciones'])
        except (ValueError, StockInsuficiente) as e:
            if str(e):
                messages.error(request, str(e))
        else:
            messages.success(request, f'Salida #{salida.pk} registrada.')
            return redirect('log_salidas_detalle', pk=salida.pk)
    return render(request, 'inventario/salida_form.html', {
        'form': form,
        'items': _items_para_lineas(),
        'lineas_previas': _lineas_previas(request.POST) if request.method == 'POST' else [],
    })


@solo_logistica
def salida_detalle(request, pk):
    salida = get_object_or_404(
        Salida.objects.select_related('bodega', 'tercero', 'creado_por')
        .prefetch_related('lineas__item'), pk=pk)
    return render(request, 'inventario/salida_detalle.html', {'salida': salida})


@solo_logistica
def traslados_lista(request):
    lista = (Traslado.objects
             .select_related('bodega_origen', 'bodega_destino', 'creado_por')
             .annotate(n_lineas=models.Count('lineas', distinct=True),
                       unidades=Coalesce(models.Sum('lineas__cantidad'), 0))
             .order_by('-creado_en'))
    return render(request, 'inventario/traslados_lista.html', {'traslados': lista})


@solo_logistica
def traslado_nuevo(request):
    form = TrasladoForm(request.POST or None)
    if request.method == 'POST':
        try:
            if not form.is_valid():
                _form_a_messages(request, form)
                raise ValueError('')
            lineas = parsear_lineas(request.POST)
            traslado = registrar_traslado(
                bodega_origen=form.cleaned_data['bodega_origen'],
                bodega_destino=form.cleaned_data['bodega_destino'],
                lineas=lineas, usuario=request.user,
                observaciones=form.cleaned_data['observaciones'])
        except (ValueError, StockInsuficiente) as e:
            if str(e):
                messages.error(request, str(e))
        else:
            messages.success(request, f'Traslado #{traslado.pk} registrado.')
            return redirect('log_traslados_detalle', pk=traslado.pk)
    return render(request, 'inventario/traslado_form.html', {
        'form': form,
        'items': _items_para_lineas(),
        'lineas_previas': _lineas_previas(request.POST) if request.method == 'POST' else [],
    })


@solo_logistica
def traslado_detalle(request, pk):
    traslado = get_object_or_404(
        Traslado.objects.select_related('bodega_origen', 'bodega_destino',
                                        'creado_por')
        .prefetch_related('lineas__item'), pk=pk)
    return render(request, 'inventario/traslado_detalle.html',
                  {'traslado': traslado})


# ---------------------------------------------------------------------------
# Préstamos y devoluciones (Fase 5)
# ---------------------------------------------------------------------------

@solo_logistica
def prestamos_lista(request):
    lista = (Prestamo.objects.select_related('tercero', 'creado_por')
             .annotate(prestado=Coalesce(models.Sum('lineas__cantidad_prestada'), 0),
                       pendiente_total=Coalesce(
                           models.Sum(models.F('lineas__cantidad_prestada')
                                      - models.F('lineas__cantidad_devuelta')), 0))
             .order_by('-creado_en'))
    return render(request, 'inventario/prestamos_lista.html', {'prestamos': lista})


@solo_logistica
def prestamo_nuevo(request):
    form = PrestamoForm(request.POST or None)
    if request.method == 'POST':
        try:
            if not form.is_valid():
                _form_a_messages(request, form)
                raise ValueError('')  # cae al re-render conservando las líneas
            lineas = parsear_lineas(request.POST, con_bodega=True)
            prestamo = crear_prestamo(
                tercero=form.cleaned_data['tercero'],
                fecha_compromiso=form.cleaned_data['fecha_compromiso'],
                lineas=lineas, usuario=request.user,
                direccion=form.cleaned_data['direccion'],
                observaciones=form.cleaned_data['observaciones'])
        except (ValueError, StockInsuficiente) as e:
            if str(e):
                messages.error(request, str(e))
        else:
            messages.success(request, f'Préstamo #{prestamo.pk} registrado.')
            return redirect('log_prestamos_detalle', pk=prestamo.pk)
    return render(request, 'inventario/prestamo_form.html', {
        'form': form,
        'items': _items_para_lineas(),
        'bodegas': Bodega.objects.filter(activa=True).order_by('nombre'),
        'lineas_previas': (_lineas_previas(request.POST, con_bodega=True)
                           if request.method == 'POST' else []),
    })


@solo_logistica
def prestamo_detalle(request, pk):
    prestamo = get_object_or_404(
        Prestamo.objects.select_related('tercero', 'creado_por')
        .prefetch_related('lineas__item', 'lineas__bodega',
                          'devoluciones__creado_por',
                          'devoluciones__movimientos__item',
                          'devoluciones__movimientos__bodega'), pk=pk)
    return render(request, 'inventario/prestamo_detalle.html',
                  {'prestamo': prestamo})


@require_POST
@solo_logistica
def prestamo_devolver(request, pk):
    """Devolución (parcial o total) desde el modal del detalle. El POST trae
    listas paralelas `dev_linea_id`/`dev_cantidad` (una fila por línea del
    préstamo); las cantidades vacías o en 0 se ignoran — devolver "algo de
    algunas líneas" es el caso normal de la devolución parcial."""
    prestamo = get_object_or_404(Prestamo, pk=pk)
    lineas_por_pk = {str(l.pk): l for l in prestamo.lineas.all()}
    lineas = []
    try:
        for linea_id, cant in zip(request.POST.getlist('dev_linea_id'),
                                  request.POST.getlist('dev_cantidad')):
            cant = cant.strip()
            if not cant or cant == '0':
                continue
            linea = lineas_por_pk.get(linea_id)
            if linea is None:
                raise ErrorDevolucion('La línea no pertenece a este préstamo.')
            try:
                cantidad = int(cant)
            except ValueError:
                raise ErrorDevolucion(
                    f'Cantidad inválida para "{linea.item.nombre}".')
            lineas.append((linea, cantidad))
        devolucion = registrar_devolucion(
            prestamo=prestamo, lineas=lineas, usuario=request.user,
            observaciones=request.POST.get('observaciones', ''))
    except (ErrorDevolucion, StockInsuficiente) as e:
        messages.error(request, str(e))
    else:
        unidades = sum(c for _, c in lineas)
        messages.success(
            request,
            f'Devolución #{devolucion.pk} registrada ({unidades} unidades).')
    return redirect('log_prestamos_detalle', pk=prestamo.pk)


# ---------------------------------------------------------------------------
# Kardex, ledger global y ajustes
# ---------------------------------------------------------------------------

def _fecha_get(request, nombre):
    try:
        return date.fromisoformat(request.GET.get(nombre, ''))
    except ValueError:
        return None


@solo_logistica
def item_kardex(request, pk):
    """Kardex de un artículo: movimientos en orden cronológico con el saldo
    por fila que dejó cada uno (`saldo_resultante`). Filtros server-side por
    bodega y rango de fechas (van por GET, son compartibles por URL)."""
    item = get_object_or_404(Item, pk=pk)
    bodega_id = request.GET.get('bodega', '')
    bodega = Bodega.objects.filter(pk=bodega_id).first() if bodega_id.isdigit() else None
    desde, hasta = _fecha_get(request, 'desde'), _fecha_get(request, 'hasta')
    movimientos = (kardex(item, bodega=bodega, desde=desde, hasta=hasta)
                   .select_related('creado_por'))
    return render(request, 'inventario/kardex.html', {
        'item': item,
        'movimientos': movimientos,
        # Todas las bodegas (también inactivas): pueden tener historial.
        'bodegas': Bodega.objects.order_by('nombre'),
        'bodega_sel': bodega,
        'desde': desde,
        'hasta': hasta,
    })


# El ledger crece sin tope; la vista muestra los últimos N y el export de la
# Fase 6 será la vía para extraer el histórico completo con filtros.
MOVIMIENTOS_MAX_FILAS = 500


@solo_logistica
def movimientos(request):
    lista = (Movimiento.objects
             .select_related('item', 'bodega', 'creado_por')
             .order_by('-creado_en', '-id')[:MOVIMIENTOS_MAX_FILAS])
    return render(request, 'inventario/movimientos.html', {
        'movimientos': lista,
        'tope': MOVIMIENTOS_MAX_FILAS,
        'tipos': Movimiento.Tipo.choices,
    })


@require_POST
@solo_logistica
def ajuste_crear(request):
    """Ajuste manual desde el modal de existencias. `registrar_ajuste` recibe
    la cantidad FINAL (absoluta) y exige motivo; el delta y el tipo de
    movimiento (AJUSTE_POS/NEG) los resuelve el servicio."""
    item_id = request.POST.get('item_id', '')
    bodega_id = request.POST.get('bodega_id', '')
    if not (item_id.isdigit() and bodega_id.isdigit()):
        messages.error(request, 'Ajuste inválido: faltan el artículo o la bodega.')
        return redirect('log_stock')
    item = get_object_or_404(Item, pk=item_id)
    bodega = get_object_or_404(Bodega, pk=bodega_id)
    try:
        nueva_cantidad = int(request.POST.get('nueva_cantidad', '').strip())
    except ValueError:
        messages.error(request, 'La nueva cantidad debe ser un número entero.')
        return redirect('log_stock')
    try:
        registrar_ajuste(item=item, bodega=bodega,
                         nueva_cantidad=nueva_cantidad, usuario=request.user,
                         motivo=request.POST.get('motivo', ''))
        messages.success(
            request,
            f'Stock de "{item.nombre}" en "{bodega.nombre}" ajustado a {nueva_cantidad}.')
    except ValueError as e:
        messages.error(request, str(e))
    return redirect('log_stock')
