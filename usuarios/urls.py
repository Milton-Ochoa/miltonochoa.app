from django.urls import path
from django.shortcuts import redirect
from . import views

urlpatterns = [
    path('login/',    views.vista_login,           name='login'),
    path('logout/',   views.vista_logout,           name='logout'),

    # Submenu separado: colegios y profesores
    path('colegios/',  views.gestionar_colegios,    name='gestionar_usuarios_colegios'),
    path('profesores/', views.gestionar_profesores, name='gestionar_usuarios_profesores'),

    # Compat: rutas legacy → redirect a colegios
    path('gestionar/', lambda r: redirect('gestionar_usuarios_colegios')),
    path('', lambda r: redirect('gestionar_usuarios_colegios'), name='gestionar_usuarios'),

    path('ajax/crear/',             views.ajax_crear_usuario,    name='ajax_crear_usuario'),
    path('ajax/editar/',            views.ajax_editar_usuario,   name='ajax_editar_usuario'),
    path('ajax/eliminar/',          views.ajax_eliminar_usuario, name='ajax_eliminar_usuario'),
    path('ajax/resetear-password/', views.ajax_resetear_password, name='ajax_resetear_password'),

    # Usuarios de etiqueta (grupo area:programacion) — gestionados desde el panel del apex.
    path('ajax/area/crear/',    views.ajax_crear_usuario_area,     name='ajax_crear_usuario_area'),
    path('ajax/area/eliminar/', views.ajax_eliminar_usuario_area,  name='ajax_eliminar_usuario_area'),
    path('ajax/area/resetear/', views.ajax_resetear_password_area, name='ajax_resetear_password_area'),
]
