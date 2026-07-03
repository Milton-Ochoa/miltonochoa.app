from django.urls import path, reverse_lazy
from django.shortcuts import redirect
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('login/',    views.vista_login,           name='login'),
    path('logout/',   views.vista_logout,           name='logout'),

    # Cambio obligatorio en el primer ingreso (empleados de área).
    path('cambiar-password/', views.cambiar_password_obligatorio, name='cambiar_password'),

    # "Olvidé mi contraseña" — auto-servicio por correo (vistas integradas de Django).
    path('reset/', auth_views.PasswordResetView.as_view(
        template_name='usuarios/password_reset_form.html',
        email_template_name='usuarios/password_reset_email.txt',
        subject_template_name='usuarios/password_reset_subject.txt',
        success_url=reverse_lazy('password_reset_done'),
    ), name='password_reset'),
    path('reset/enviado/', auth_views.PasswordResetDoneView.as_view(
        template_name='usuarios/password_reset_done.html',
    ), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', views.EmpleadoPasswordResetConfirmView.as_view(
        template_name='usuarios/password_reset_confirm.html',
        success_url=reverse_lazy('password_reset_complete'),
    ), name='password_reset_confirm'),
    path('reset/listo/', auth_views.PasswordResetCompleteView.as_view(
        template_name='usuarios/password_reset_complete.html',
    ), name='password_reset_complete'),

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
    path('ajax/area/editar/',   views.ajax_editar_usuario_area,    name='ajax_editar_usuario_area'),
    path('ajax/area/eliminar/', views.ajax_eliminar_usuario_area,  name='ajax_eliminar_usuario_area'),
    path('ajax/area/resetear/', views.ajax_resetear_password_area, name='ajax_resetear_password_area'),

    # Permisos granulares por módulo (modal del panel del apex).
    path('ajax/area/permisos/',         views.ajax_permisos_usuario,         name='ajax_permisos_usuario'),
    path('ajax/area/permisos/guardar/', views.ajax_guardar_permisos_usuario, name='ajax_guardar_permisos_usuario'),

    # Telemetría: capturador casero de errores del navegador (base_chrome.html → /admin/).
    path('telemetria/error/', views.telemetria_error_cliente, name='telemetria_error_cliente'),
]
