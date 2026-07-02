from django.db import models
from django.contrib.auth.models import User
from programacion.configuracion.models import Colegio, Profesor


class UsuarioColegio(models.Model):
    """
    Vincula un User de Django a un Colegio, otorgándole el rol de gestor de colegio.
    OneToOne garantiza un único colegio por usuario. El middleware inyecta el año
    activo más reciente en `request.colegio_anio_activo` para cada request.
    """
    user    = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil_colegio')
    colegio = models.ForeignKey(Colegio, on_delete=models.CASCADE, related_name='usuarios')

    class Meta:
        db_table            = 'usuarios_colegio'
        verbose_name        = "Usuario de Colegio"
        verbose_name_plural = "Usuarios de Colegios"

    def __str__(self):
        return f"{self.user.username} → {self.colegio.nombre}"


class UsuarioProfesor(models.Model):
    """
    Vincula un User de Django a un Profesor, otorgándole acceso solo a su propio horario.
    Las vistas de profesores leen `request.perfil_profesor` para forzar el scope al profesor
    del perfil, ignorando cualquier `profesor_id` que el usuario intente manipular en la URL.
    """
    user     = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil_profesor')
    profesor = models.ForeignKey(Profesor, on_delete=models.CASCADE, related_name='usuarios')

    class Meta:
        db_table            = 'usuarios_profesor'
        verbose_name        = "Usuario de Profesor"
        verbose_name_plural = "Usuarios de Profesores"

    def __str__(self):
        return f"{self.user.username} → {self.profesor.nombre}"


class PerfilEmpleado(models.Model):
    """
    Credencial de un empleado de área (usuario "de etiqueta": grupo `area:programacion`/
    `area:financiera`). A diferencia de colegio/profesor no vincula un dominio: solo guarda
    el estado de la contraseña.

    `debe_cambiar_password` arranca en True al crearlo (clave genérica que asigna el admin) y
    cada vez que el admin la resetea; el middleware obliga a cambiarla en el primer ingreso y
    la pone en False cuando el empleado elige su propia clave (cambio forzado o reset por correo).
    El correo del empleado vive en `User.email` (lo usa el flujo de "olvidé mi contraseña").
    """
    user                  = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil_empleado')
    debe_cambiar_password = models.BooleanField(default=True)

    class Meta:
        db_table            = 'usuarios_empleados'
        verbose_name        = "Perfil de Empleado"
        verbose_name_plural = "Perfiles de Empleados"

    def __str__(self):
        return f"{self.user.username} (empleado)"


class ModuloUsuario(models.Model):
    """Override de acceso de un usuario a un **módulo** de un área (permisos granulares).

    Solo se guardan overrides (tabla **sparse**): sin filas, el comportamiento es el
    histórico (grupo `area:<area>` → todo el área COMPLETO; sin grupo → sin acceso). Cada
    fila pisa el nivel base de UN módulo del catálogo (`core/modulos.py`) para UN área,
    permitiendo: quitar un módulo (SIN_ACCESO), ponerlo en solo lectura (LECTURA), o dar
    acceso cruzado a un módulo de otra área sin otorgar el área completa (COMPLETO sobre
    una base sin grupo). La resolución vive en `usuarios/permisos.py`.
    """
    class Nivel(models.TextChoices):
        SIN_ACCESO = 'SIN', 'Sin acceso'
        LECTURA    = 'LEC', 'Solo lectura'
        COMPLETO   = 'COM', 'Completo'

    user   = models.ForeignKey(User, on_delete=models.CASCADE, related_name='modulos_override')
    area   = models.CharField(max_length=20)   # slug de core.areas.AREAS
    modulo = models.CharField(max_length=40)   # slug del catálogo core/modulos.py
    nivel  = models.CharField(max_length=3, choices=Nivel.choices)
    actualizado_por = models.ForeignKey(User, null=True, blank=True,
                                        on_delete=models.SET_NULL, related_name='+')
    actualizado_en  = models.DateTimeField(auto_now=True)

    class Meta:
        db_table            = 'usuarios_modulos'
        verbose_name        = "Override de módulo"
        verbose_name_plural = "Overrides de módulo"
        constraints = [
            models.UniqueConstraint(fields=['user', 'area', 'modulo'],
                                    name='unique_modulo_por_usuario'),
        ]

    def __str__(self):
        return f"{self.user.username} · {self.area}/{self.modulo} = {self.get_nivel_display()}"


class ErrorCliente(models.Model):
    """
    Diagnóstico casero: registro de errores ocurridos en el NAVEGADOR (JS, promesas
    rechazadas, fetch fallido) enviados por el capturador de `base_chrome.html`.

    Existe porque los errores que describe el usuario son INTERMITENTES y bajo carga
    ("se cuelga al hacer muchas cosas rápido"); un `console.log` no sirve (hay que estar
    mirando justo en el instante y el reload lo borra) y los logs de Railway son efímeros.
    Aquí queda persistido y consultable en /admin/, con el contexto del instante: los
    últimos clics y fetches del usuario (`breadcrumbs`) antes del fallo.
    """
    creado_en   = models.DateTimeField(auto_now_add=True)
    usuario     = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='errores_cliente')
    area        = models.CharField(max_length=30, blank=True)
    tipo        = models.CharField(max_length=30)   # error | promesa | fetch | http
    mensaje     = models.TextField(blank=True)
    stack       = models.TextField(blank=True)
    url         = models.TextField(blank=True)
    user_agent  = models.TextField(blank=True)
    breadcrumbs = models.JSONField(default=list, blank=True)   # [{t, tipo, detalle}, …]
    extra       = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table            = 'usuarios_errores_cliente'
        verbose_name        = "Error de cliente"
        verbose_name_plural = "Errores de cliente"
        ordering            = ['-creado_en']

    def __str__(self):
        return f"[{self.tipo}] {self.mensaje[:60]} ({self.creado_en:%Y-%m-%d %H:%M})"