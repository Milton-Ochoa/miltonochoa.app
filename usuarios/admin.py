from django.contrib import admin

from .models import ErrorCliente, ModuloUsuario


@admin.register(ModuloUsuario)
class ModuloUsuarioAdmin(admin.ModelAdmin):
    """Overrides de permisos por módulo. Editable a mano para pruebas antes de la UI del
    panel (FASE 5); la fuente de verdad del alta/baja sigue siendo el catálogo + la
    resolución (`usuarios/permisos.py`)."""
    list_display   = ('user', 'area', 'modulo', 'nivel', 'actualizado_por', 'actualizado_en')
    list_filter    = ('area', 'nivel')
    search_fields  = ('user__username',)
    autocomplete_fields = ('user', 'actualizado_por')


@admin.register(ErrorCliente)
class ErrorClienteAdmin(admin.ModelAdmin):
    """Solo lectura: el capturador del navegador es la única fuente; aquí se consultan."""
    list_display    = ('creado_en', 'tipo', 'area', 'usuario', '_mensaje_corto', 'url')
    list_filter     = ('tipo', 'area', 'creado_en')
    search_fields   = ('mensaje', 'stack', 'url', 'usuario__username')
    date_hierarchy  = 'creado_en'
    ordering        = ('-creado_en',)
    readonly_fields = ('creado_en', 'usuario', 'area', 'tipo', 'mensaje', 'stack',
                       'url', 'user_agent', 'breadcrumbs', 'extra')

    @admin.display(description='Mensaje')
    def _mensaje_corto(self, obj):
        return (obj.mensaje or '')[:80]

    def has_add_permission(self, request):
        return False  # nunca se crean a mano; los manda el navegador
