"""El artículo pasa de (código, nombre) a (categoría, referencia, grado).

No hay migración de datos posible: un artículo viejo no dice a qué grado
pertenece, así que la conversión sería una invención. El usuario respaldó el
inventario y aprobó empezar de cero, de modo que esta migración BORRA los
datos operativos (ledger, stock, documentos y artículos) y conserva los
catálogos: bodegas, categorías y terceros.

**`atomic = False` es obligatorio aquí (no es una preferencia).** Django crea las
FK como DEFERRABLE INITIALLY DEFERRED, así que dentro de una transacción los
DELETE dejan sus eventos de trigger ENCOLADOS hasta el commit y PostgreSQL
aborta cualquier ALTER TABLE posterior sobre esas tablas con «cannot ALTER TABLE
"log_articulos" because it has pending trigger events» — eso tumbó el primer
deploy de esta migración y dejó la app en 502. Sin transacción envolvente, cada
DELETE hace commit al instante y la cola queda vacía antes de los ALTER. SQLite
no tiene constraints diferidas, por eso los tests NUNCA reprodujeron el fallo:
una migración destructiva sobre PostgreSQL no se valida con la suite.

Contrapartida asumida: si algo falla a mitad, la migración queda a medio aplicar
y sin registrar (hay que reparar a mano desde el respaldo). Se acepta porque el
borrado ya es irreversible por diseño.

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


def vaciar_triggers_pendientes(apps, schema_editor):
    """Segundo cinturón por si alguien vuelve a poner `atomic = True`.

    Con la migración no atómica la cola de triggers ya está vacía y esto es un
    no-op; dentro de una transacción, en cambio, es lo único que evita repetir
    el incidente. Cuesta una sentencia. En SQLite no existe la sintaxis.
    """
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('SET CONSTRAINTS ALL IMMEDIATE')


def irreversible(apps, schema_editor):
    raise RuntimeError(
        'La remodelación del artículo no es reversible: los datos operativos '
        'del inventario se borraron. Restaura desde el respaldo.')


class Migration(migrations.Migration):

    atomic = False  # ver el docstring: sin esto PostgreSQL aborta los ALTER

    dependencies = [
        ('log_inventario', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(borrar_datos_operativos, irreversible),
        migrations.RunPython(vaciar_triggers_pendientes, migrations.RunPython.noop),
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
