from django.contrib import admin
from django.db.models import Count
from .models import NombreLibro, Materia, Unidad, Colegio, ColegioAnio, Profesor


@admin.register(Materia)
class MateriaAdmin(admin.ModelAdmin):
    list_display  = ('nombre', 'color')
    search_fields = ('nombre',)


@admin.register(NombreLibro)
class NombreLibroAdmin(admin.ModelAdmin):
    list_display  = ('nombre', 'activo', 'num_unidades')
    list_filter   = ('activo',)
    search_fields = ('nombre',)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_num_unidades=Count('unidades'))

    @admin.display(description='Unidades')
    def num_unidades(self, obj):
        return obj._num_unidades


@admin.register(Unidad)
class UnidadAdmin(admin.ModelAdmin):
    list_display  = ('libro', 'materia', 'numero', 'nombre')
    list_filter   = ('libro', 'materia')
    search_fields = ('libro__nombre', 'materia__nombre', 'nombre')
    ordering      = ('libro__nombre', 'materia__nombre', 'numero')


class ColegioAnioInline(admin.TabularInline):
    model = ColegioAnio
    extra = 0


@admin.register(Colegio)
class ColegioAdmin(admin.ModelAdmin):
    list_display  = ('nombre', 'ciudad', 'mapa_link')
    search_fields = ('nombre', 'ciudad')
    ordering      = ('nombre',)
    inlines       = [ColegioAnioInline]


@admin.register(ColegioAnio)
class ColegioAnioAdmin(admin.ModelAdmin):
    list_display  = ('colegio', 'anio', 'activo')
    list_filter   = ('anio', 'activo')
    search_fields = ('colegio__nombre',)
    ordering      = ('colegio__nombre', '-anio')


@admin.register(Profesor)
class ProfesorAdmin(admin.ModelAdmin):
    list_display    = ('nombre_corto', 'documento', 'email', 'celular', 'ciudad')
    search_fields   = ('nombre', 'apellido', 'documento', 'email')
    list_filter     = ('ciudad', 'disponibilidad', 'banco')
    ordering        = ('nombre',)
    readonly_fields = ('nombre_corto',)
