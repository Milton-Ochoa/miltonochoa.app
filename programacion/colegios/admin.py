from django.contrib import admin
from .models import Bloque, Clase, Asignacion, HistorialCambio

@admin.register(Bloque)
class BloqueAdmin(admin.ModelAdmin):
    list_display  = ('colegio', 'grado', 'hora')
    list_filter   = ('colegio', 'grado')
    search_fields = ('colegio__nombre', 'grado')


@admin.register(Clase)
class ClaseAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'colegio', 'bloque', 'profesor', 'materia')
    list_filter  = ('fecha', 'colegio', 'profesor')


@admin.register(Asignacion)
class AsignacionAdmin(admin.ModelAdmin):
    list_display = ('colegio', 'grado', 'libro')
    list_filter  = ('colegio',)


@admin.register(HistorialCambio)
class HistorialCambioAdmin(admin.ModelAdmin):
    list_display  = ('fecha', 'tipo', 'objeto_tipo', 'objeto_str', 'colegio', 'usuario')
    list_filter   = ('tipo', 'objeto_tipo', 'colegio', 'fecha')
    search_fields = ('objeto_str', 'usuario__username', 'detalle')
    date_hierarchy = 'fecha'
    readonly_fields = ('objeto_tipo', 'objeto_id', 'objeto_str', 'colegio',
                       'tipo', 'usuario', 'fecha', 'detalle')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
