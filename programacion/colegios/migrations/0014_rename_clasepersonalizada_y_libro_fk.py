import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Renombra ClaseParticular → ClasePersonalizada (modelo + tabla) y agrega la
    FK `libro` al catálogo de libros. El campo de texto `material` se conserva
    hasta la migración de datos 0015 (que lo convierte a FK) y se elimina en 0016.
    """

    dependencies = [
        ('colegios', '0013_rename_colegios_as_colegio_d3b9b1_idx_prog_asigna_colegio_45aa3e_idx_and_more'),
        ('configuracion', '0019_nombrelibro_es_material_asignado'),
        # El rename del modelo debe correr DESPUÉS de todas las migraciones de
        # informes que aún referencian el nombre viejo (FK a colegios.claseparticular).
        # Sin esto, en una BD nueva el ejecutor podría renombrar antes de crear el
        # informe y la FK no resolvería ("colegios.claseparticular cannot be resolved").
        ('informes', '0003_alter_informe_table'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='ClaseParticular',
            new_name='ClasePersonalizada',
        ),
        migrations.AlterModelTable(
            name='clasepersonalizada',
            table='prog_clases_personalizadas',
        ),
        migrations.AlterModelOptions(
            name='clasepersonalizada',
            options={'verbose_name': 'Clase Personalizada', 'verbose_name_plural': 'Clases Personalizadas'},
        ),
        migrations.AddField(
            model_name='clasepersonalizada',
            name='libro',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to='configuracion.nombrelibro',
                verbose_name='Libro / Material',
            ),
        ),
    ]
