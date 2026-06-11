"""Crea el grupo 'area:logistica' (etiqueta de acceso al área logística).

Espejo de las migraciones que crearon 'area:programacion' y 'area:financiera'.
Los usuarios de etiqueta se gestionan desde el panel del apex (GRUPOS_ETIQUETA);
el login los lleva a logistica.miltonochoa.app y el middleware les concede acceso
al área (ver core.areas.es_personal_logistica). Idempotente: get_or_create.
"""
from django.db import migrations

NOMBRE_GRUPO = 'area:logistica'


def crear_grupo(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.get_or_create(name=NOMBRE_GRUPO)


def borrar_grupo(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name=NOMBRE_GRUPO).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0008_errorcliente'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(crear_grupo, borrar_grupo),
    ]
