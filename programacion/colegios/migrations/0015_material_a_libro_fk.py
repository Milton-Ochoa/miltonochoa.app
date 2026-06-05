from django.db import migrations


def material_a_libro(apps, schema_editor):
    """Convierte el texto `material` (nombre del libro) en la FK `libro` (id).

    Las clases de Socialización guardaban material='S' (y unidad='S'): se dejan
    con libro=null. Si el nombre no coincide con ningún libro del catálogo
    (datos heredados sueltos), también queda null para no inventar referencias.
    """
    ClasePersonalizada = apps.get_model('colegios', 'ClasePersonalizada')
    NombreLibro = apps.get_model('configuracion', 'NombreLibro')

    libros_por_nombre = {l.nombre: l.id for l in NombreLibro.objects.all()}

    for cp in ClasePersonalizada.objects.all():
        nombre = (cp.material or '').strip()
        if not nombre or nombre in ('S', 'A'):
            continue  # socialización / sin libro → libro queda null
        libro_id = libros_por_nombre.get(nombre)
        if libro_id:
            cp.libro_id = libro_id
            cp.save(update_fields=['libro'])


def libro_a_material(apps, schema_editor):
    """Reverso: reconstruye el texto `material` desde la FK (o 'S' en socialización)."""
    ClasePersonalizada = apps.get_model('colegios', 'ClasePersonalizada')
    for cp in ClasePersonalizada.objects.select_related('libro').all():
        if str(cp.unidad) == 'S':
            cp.material = 'S'
        elif cp.libro_id:
            cp.material = cp.libro.nombre
        else:
            cp.material = ''
        cp.save(update_fields=['material'])


class Migration(migrations.Migration):

    dependencies = [
        ('colegios', '0014_rename_clasepersonalizada_y_libro_fk'),
    ]

    operations = [
        migrations.RunPython(material_a_libro, libro_a_material),
    ]
