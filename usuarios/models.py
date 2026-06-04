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