from django.db import migrations, models


class Migration(migrations.Migration):
    """Renombra el campo FK `clase_particular` → `clase_personalizada` (columna
    `clase_particular_id` → `clase_personalizada_id`) para alinear informes con
    el modelo renombrado. El CheckConstraint referencia el campo, así que se
    elimina antes del rename y se recrea después con el nombre nuevo.
    """

    dependencies = [
        ('informes', '0002_informe_informe_exactamente_una_clase'),
        ('informes', '0003_alter_informe_table'),
        ('colegios', '0014_rename_clasepersonalizada_y_libro_fk'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='informe',
            name='informe_exactamente_una_clase',
        ),
        migrations.RenameField(
            model_name='informe',
            old_name='clase_particular',
            new_name='clase_personalizada',
        ),
        migrations.AddConstraint(
            model_name='informe',
            constraint=models.CheckConstraint(
                check=(
                    models.Q(clase__isnull=False, clase_personalizada__isnull=True) |
                    models.Q(clase__isnull=True, clase_personalizada__isnull=False)
                ),
                name='informe_exactamente_una_clase',
            ),
        ),
    ]
