from django.contrib import admin

from .models import GastoViatico, SolicitudViatico


class GastoViaticoInline(admin.TabularInline):
    model = GastoViatico
    extra = 0


@admin.register(SolicitudViatico)
class SolicitudViaticoAdmin(admin.ModelAdmin):
    list_display  = ('id', 'docente_nombre', 'colegio_nombre', 'estado',
                     'fecha_viaje', 'fecha_regreso', 'creado_en')
    list_filter   = ('estado',)
    search_fields = ('docente_nombre', 'docente_cedula', 'colegio_nombre')
    date_hierarchy = 'creado_en'
    inlines = [GastoViaticoInline]
