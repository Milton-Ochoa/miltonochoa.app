from django.contrib import admin

from .models import AsignacionMonitor, ColegioSimulacro, Monitor, Simulacro


@admin.register(Monitor)
class MonitorAdmin(admin.ModelAdmin):
    list_display  = ('nombre', 'apellido', 'documento', 'ciudad', 'activo')
    list_filter   = ('activo', 'departamento', 'banco')
    search_fields = ('nombre', 'apellido', 'documento')


@admin.register(ColegioSimulacro)
class ColegioSimulacroAdmin(admin.ModelAdmin):
    list_display  = ('nombre', 'codigo', 'ciudad', 'departamento', 'activo')
    list_filter   = ('activo', 'departamento')
    search_fields = ('nombre', 'codigo', 'ciudad')


class AsignacionMonitorInline(admin.TabularInline):
    model = AsignacionMonitor
    extra = 0
    autocomplete_fields = ('monitor',)


@admin.register(Simulacro)
class SimulacroAdmin(admin.ModelAdmin):
    list_display  = ('nombre_colegio', 'fecha', 'jornada', 'valor')
    list_filter   = ('jornada', 'fecha')
    search_fields = ('colegio__nombre', 'colegio_nombre')
    filter_horizontal = ('grados',)
    inlines       = (AsignacionMonitorInline,)
