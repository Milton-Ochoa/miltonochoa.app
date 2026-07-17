from django.contrib import admin

from .models import (ArticuloERP, AsignacionBodega, CargaReporte, EventoOrden,
                     LineaOrden, OrdenDespacho)


@admin.register(ArticuloERP)
class ArticuloERPAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'descripcion', 'categoria')
    list_filter = ('categoria',)
    search_fields = ('codigo', 'descripcion')


class LineaOrdenInline(admin.TabularInline):
    model = LineaOrden
    extra = 0
    fields = ('cod_articulo', 'descripcion', 'categoria', 'cantidad',
              'es_material', 'articulo_cambio', 'cantidad_cambio', 'pendiente_erp',
              'eliminada_erp')
    readonly_fields = ('cod_articulo', 'descripcion', 'categoria', 'cantidad',
                       'es_material')


@admin.register(OrdenDespacho)
class OrdenDespachoAdmin(admin.ModelAdmin):
    list_display = ('id_orden', 'cliente', 'bodega', 'estado', 'fecha_entrega',
                    'es_despachable', 'alerta_remision', 'cerrada_sin_marcar')
    list_filter = ('estado', 'bodega', 'es_despachable', 'alerta_remision',
                   'vigencia')
    search_fields = ('id_orden', 'cliente', 'ciudad')
    date_hierarchy = 'fecha_entrega'
    inlines = [LineaOrdenInline]


@admin.register(AsignacionBodega)
class AsignacionBodegaAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'bodega', 'asignado_por', 'asignado_en')
    search_fields = ('usuario__username', 'bodega')


@admin.register(CargaReporte)
class CargaReporteAdmin(admin.ModelAdmin):
    """Bitácora de importaciones: solo lectura (la crea el import)."""
    list_display = ('id', 'creado_en', 'usuario', 'nombre_archivo',
                    'max_fecha_orden', 'n_ordenes', 'n_nuevas', 'n_actualizadas',
                    'n_cerradas_auto', 'n_descartadas')
    date_hierarchy = 'creado_en'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(EventoOrden)
class EventoOrdenAdmin(admin.ModelAdmin):
    """Bitácora append-only (patrón Movimiento): lectura pura, nunca se edita
    ni se borra."""
    list_display = ('creado_en', 'tipo', 'orden', 'detalle', 'usuario', 'carga')
    list_filter = ('tipo',)
    search_fields = ('orden__id_orden', 'detalle')
    date_hierarchy = 'creado_en'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
