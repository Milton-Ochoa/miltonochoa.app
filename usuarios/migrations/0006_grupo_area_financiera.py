"""Crea el grupo 'area:financiera' (etiqueta de acceso al área financiera).

Espejo de la migración que creó 'area:programacion'. Por ahora la asignación de
usuarios a este grupo se hace desde /admin/ (no hay CRUD propio todavía); el login
los lleva a financiera.miltonochoa.app y el middleware les concede acceso al área
(ver core.areas.es_personal_financiera). Idempotente: get_or_create.
"""
from django.db import migrations

NOMBRE_GRUPO = 'area:financiera'


def crear_grupo(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.get_or_create(name=NOMBRE_GRUPO)


def borrar_grupo(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name=NOMBRE_GRUPO).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0005_alter_usuariocolegio_table_and_more'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(crear_grupo, borrar_grupo),
    ]
