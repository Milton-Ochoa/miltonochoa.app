from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('configuracion', '0020_drop_nombrelibro_enlace'),
    ]

    operations = [
        migrations.AddField(
            model_name='colegioanio',
            name='valor_hora',
            field=models.IntegerField(
                blank=True,
                null=True,
                verbose_name='Valor por Hora (COP)',
                help_text='Valor en pesos colombianos que se paga por hora de clase en este colegio/año',
            ),
        ),
    ]
