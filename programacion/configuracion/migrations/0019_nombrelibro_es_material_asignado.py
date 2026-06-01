from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('configuracion', '0018_material_especial_libro_enlace'),
    ]

    operations = [
        migrations.AddField(
            model_name='nombrelibro',
            name='es_material_asignado',
            field=models.BooleanField(default=False, verbose_name='Es Material Asignado'),
        ),
    ]
