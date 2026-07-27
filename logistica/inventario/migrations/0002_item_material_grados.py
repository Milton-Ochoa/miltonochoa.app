"""El artículo pasa de (código, nombre) a (categoría, referencia, grado).

No hay migración de datos posible: un artículo viejo no dice a qué grado
pertenece, así que la conversión sería una invención. El usuario respaldó el
inventario y aprobó empezar de cero, de modo que esta migración BORRA los
datos operativos (ledger, stock, documentos y artículos) y conserva los
catálogos: bodegas, categorías y terceros.

OJO: los archivos de `AdjuntoEntrada` quedan huérfanos en el storage (el
borrado por queryset no toca los ficheros); se limpian a mano si estorban.
"""
from django.db import migrations, models


def borrar_datos_operativos(apps, schema_editor):
    # Orden dictado por los PROTECT: primero el ledger (protege a artículos,
    # bodegas y documentos), luego los documentos de arriba hacia abajo.
    for etiqueta in ('Movimiento', 'Devolucion', 'Prestamo', 'Entrada',
                     'Salida', 'Traslado', 'Stock', 'Item'):
        apps.get_model('log_inventario', etiqueta).objects.all().delete()


def irreversible(apps, schema_editor):
    raise RuntimeError(
        'La remodelación del artículo no es reversible: los datos operativos '
        'del inventario se borraron. Restaura desde el respaldo.')


class Migration(migrations.Migration):

    dependencies = [
        ('log_inventario', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(borrar_datos_operativos, irreversible),
        migrations.AlterModelOptions(
            name='item',
            options={'ordering': ['categoria__nombre', 'referencia', 'grado'],
                     'verbose_name': 'Artículo'},
        ),
        migrations.RemoveField(model_name='item', name='codigo'),
        migrations.RemoveField(model_name='item', name='nombre'),
        migrations.AddField(
            model_name='item',
            name='referencia',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='item',
            name='grado',
            # default solo para el ALTER (la tabla ya quedó vacía arriba).
            field=models.PositiveSmallIntegerField(default=0),
            preserve_default=False,
        ),
        migrations.AddConstraint(
            model_name='item',
            constraint=models.UniqueConstraint(
                fields=('categoria', 'referencia', 'grado'),
                name='unique_item_material_grado'),
        ),
        migrations.AddConstraint(
            model_name='item',
            constraint=models.CheckConstraint(
                condition=models.Q(('grado__lte', 11)),
                name='item_grado_valido'),
        ),
    ]
