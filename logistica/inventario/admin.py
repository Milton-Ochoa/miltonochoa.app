from django.contrib import admin

from .models import (AdjuntoEntrada, Bodega, Categoria, Devolucion, Entrada,
                     EntradaLinea, Item, Movimiento, Prestamo, PrestamoLinea,
                     Salida, SalidaLinea, Stock, Tercero, Traslado,
                     TrasladoLinea)


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    search_fields = ('nombre',)


@admin.register(Bodega)
class BodegaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'ubicacion', 'activa')
    list_filter = ('activa',)


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ('categoria', 'referencia', 'grado', 'unidad_medida',
                    'stock_minimo', 'activo')
    list_filter = ('categoria', 'grado', 'activo')
    search_fields = ('referencia', 'categoria__nombre')


@admin.register(Tercero)
class TerceroAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'documento', 'telefono', 'activo')
    search_fields = ('nombre', 'documento')


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    """Solo consulta: el stock lo escriben los servicios (services.py).
    Corregir un saldo desde aquí rompería el kardex — usar un ajuste."""
    list_display = ('item', 'bodega', 'cantidad')
    list_filter = ('bodega',)
    search_fields = ('item__referencia', 'item__categoria__nombre')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Movimiento)
class MovimientoAdmin(admin.ModelAdmin):
    """Ledger append-only: lectura pura, nunca se edita ni se borra (los
    errores se corrigen con un contramovimiento/ajuste)."""
    list_display = ('creado_en', 'tipo', 'item', 'bodega', 'cantidad',
                    'saldo_resultante', 'detalle', 'creado_por')
    list_filter = ('tipo', 'bodega')
    search_fields = ('item__referencia', 'item__categoria__nombre', 'detalle')
    date_hierarchy = 'creado_en'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class EntradaLineaInline(admin.TabularInline):
    model = EntradaLinea
    extra = 0


class AdjuntoEntradaInline(admin.TabularInline):
    model = AdjuntoEntrada
    extra = 0
    readonly_fields = ('subido_por', 'subido_en')


@admin.register(Entrada)
class EntradaAdmin(admin.ModelAdmin):
    list_display = ('id', 'bodega', 'proveedor', 'creado_por', 'creado_en')
    list_filter = ('bodega',)
    inlines = [EntradaLineaInline, AdjuntoEntradaInline]


class SalidaLineaInline(admin.TabularInline):
    model = SalidaLinea
    extra = 0


@admin.register(Salida)
class SalidaAdmin(admin.ModelAdmin):
    list_display = ('id', 'bodega', 'tercero_nombre', 'motivo', 'creado_por',
                    'creado_en')
    list_filter = ('bodega',)
    search_fields = ('tercero_nombre',)
    inlines = [SalidaLineaInline]


class TrasladoLineaInline(admin.TabularInline):
    model = TrasladoLinea
    extra = 0


@admin.register(Traslado)
class TrasladoAdmin(admin.ModelAdmin):
    list_display = ('id', 'bodega_origen', 'bodega_destino', 'creado_por',
                    'creado_en')
    inlines = [TrasladoLineaInline]


class PrestamoLineaInline(admin.TabularInline):
    model = PrestamoLinea
    extra = 0


@admin.register(Prestamo)
class PrestamoAdmin(admin.ModelAdmin):
    list_display = ('id', 'direccion', 'tercero_nombre', 'fecha_compromiso',
                    'estado', 'creado_en')
    list_filter = ('direccion', 'estado')
    search_fields = ('tercero_nombre',)
    inlines = [PrestamoLineaInline]


@admin.register(Devolucion)
class DevolucionAdmin(admin.ModelAdmin):
    list_display = ('id', 'prestamo', 'creado_por', 'creado_en')
