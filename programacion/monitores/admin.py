from django.contrib import admin

from .models import ColegioSimulacro, Monitor


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
