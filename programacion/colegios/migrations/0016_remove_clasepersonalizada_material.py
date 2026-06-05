from django.db import migrations


class Migration(migrations.Migration):
    """Elimina el campo de texto `material`, ya convertido a la FK `libro` (0015).

    El reverso de RemoveField recrea la columna desde el estado histórico, así
    que 0015 puede repoblarla al revertir.
    """

    dependencies = [
        ('colegios', '0015_material_a_libro_fk'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='clasepersonalizada',
            name='material',
        ),
    ]
