"""Crea el grupo 'area:programacion' (etiqueta de acceso staff al área programación).

Los usuarios que el superusuario crea desde el panel se añaden a este grupo; el
login los lleva a programacion.miltonochoa.app y el middleware les concede acceso
completo al área (ver core.areas.es_personal_programacion). Idempotente: usa
get_or_create, así que repetir la migración o ejecutarla con el grupo ya existente
no falla.
"""
from django.db import migrations

NOMBRE_GRUPO = 'area:programacion'


def crear_grupo(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.get_or_create(name=NOMBRE_GRUPO)


def borrar_grupo(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name=NOMBRE_GRUPO).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0003_eliminar_password_texto'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(crear_grupo, borrar_grupo),
    ]
