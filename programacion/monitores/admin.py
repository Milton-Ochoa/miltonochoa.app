from django.contrib import admin

from .models import Monitor


@admin.register(Monitor)
class MonitorAdmin(admin.ModelAdmin):
    list_display  = ('nombre', 'apellido', 'documento', 'ciudad', 'activo')
    list_filter   = ('activo', 'departamento', 'banco')
    search_fields = ('nombre', 'apellido', 'documento')
