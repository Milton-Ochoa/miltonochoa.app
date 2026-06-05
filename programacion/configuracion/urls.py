from django.urls import path, include
from .views import (
    configuracion_libros, configuracion_colegios, configuracion_profesores,
    ajax_ciudades,
    ajax_crear_libro, ajax_editar_libro,
    ajax_toggle_libro, ajax_toggle_material_asignado, ajax_eliminar_libro,
    ajax_unidades_libro, ajax_crear_unidad, ajax_editar_unidad, ajax_eliminar_unidad,
    ajax_materias, ajax_crear_materia, ajax_editar_materia, ajax_eliminar_materia,
    ajax_documentos_profesor, ajax_subir_documento_profesor,
    ajax_eliminar_documento_profesor, documento_profesor_descargar,
)

urlpatterns = [
    # ── Vistas principales ──
    path('libros/',     configuracion_libros,     name='configuracion_libros'),
    path('colegios/',   configuracion_colegios,   name='configuracion_colegios'),
    path('profesores/', configuracion_profesores, name='configuracion_profesores'),

    # ── AJAX geo ──
    path('ajax/ciudades/', ajax_ciudades, name='ajax_ciudades'),

    # ── AJAX libros ──
    path('ajax/libros/crear/',              ajax_crear_libro,   name='ajax_crear_libro'),
    path('ajax/libros/<int:libro_id>/editar/',   ajax_editar_libro,  name='ajax_editar_libro'),
path('ajax/libros/<int:libro_id>/toggle/',              ajax_toggle_libro,            name='ajax_toggle_libro'),
    path('ajax/libros/<int:libro_id>/toggle-material/',    ajax_toggle_material_asignado, name='ajax_toggle_material_asignado'),
    path('ajax/libros/<int:libro_id>/eliminar/', ajax_eliminar_libro, name='ajax_eliminar_libro'),
    path('ajax/libros/<int:libro_id>/unidades/', ajax_unidades_libro, name='ajax_unidades_libro'),

    # ── AJAX unidades ──
    path('ajax/unidades/crear/',                 ajax_crear_unidad,   name='ajax_crear_unidad'),
    path('ajax/unidades/<int:unidad_id>/editar/', ajax_editar_unidad,  name='ajax_editar_unidad'),
    path('ajax/unidades/<int:unidad_id>/eliminar/', ajax_eliminar_unidad, name='ajax_eliminar_unidad'),

    # ── AJAX materias ──
    path('ajax/materias/',                       ajax_materias,       name='ajax_materias'),
    path('ajax/materias/crear/',                 ajax_crear_materia,  name='ajax_crear_materia'),
    path('ajax/materias/<int:materia_id>/editar/', ajax_editar_materia,  name='ajax_editar_materia'),
    path('ajax/materias/<int:materia_id>/eliminar/', ajax_eliminar_materia, name='ajax_eliminar_materia'),

    # ── Documentos de profesor (CV, cédula, RUT, …) ──
    path('ajax/profesores/<int:profesor_id>/documentos/',       ajax_documentos_profesor,        name='ajax_documentos_profesor'),
    path('ajax/profesores/<int:profesor_id>/documentos/subir/', ajax_subir_documento_profesor,   name='ajax_subir_documento_profesor'),
    path('ajax/documentos/<int:documento_id>/eliminar/',        ajax_eliminar_documento_profesor, name='ajax_eliminar_documento_profesor'),
    path('profesores/documentos/<int:documento_id>/descargar/', documento_profesor_descargar,    name='documento_profesor_descargar'),
]