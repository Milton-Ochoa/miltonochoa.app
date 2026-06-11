# Backfill: las clases que ya estaban canceladas (checkbox histórico, siempre
# por colegio) deben aparecer en el reporte de Cancelaciones desde el día uno.
# Se crea su registro COLEGIO con snapshot del estado actual y sin usuario
# (no sabemos quién las canceló).
from django.db import migrations


def backfill_cancelaciones(apps, schema_editor):
    Clase = apps.get_model('colegios', 'Clase')
    CancelacionClase = apps.get_model('colegios', 'CancelacionClase')

    canceladas = (
        Clase.objects
        .filter(cancelada=True)
        .select_related('profesor', 'colegio__colegio')
    )
    registros = []
    for clase in canceladas.iterator():
        profesor = clase.profesor
        colegio = clase.colegio.colegio if clase.colegio_id else None
        registros.append(CancelacionClase(
            clase=clase,
            tipo='COLEGIO',
            profesor=profesor,
            profesor_nombre=(
                f'{profesor.nombre} {profesor.apellido}'.strip() if profesor else ''
            ),
            colegio=colegio,
            colegio_nombre=colegio.nombre if colegio else '',
            fecha_clase=clase.fecha,
            motivo=clase.comentarios or '',
            registrado_por=None,
        ))
    CancelacionClase.objects.bulk_create(registros, batch_size=500)


def revertir_backfill(apps, schema_editor):
    # Solo elimina lo que este backfill pudo crear (COLEGIO sin usuario);
    # los registros creados por la UI llevan registrado_por.
    CancelacionClase = apps.get_model('colegios', 'CancelacionClase')
    CancelacionClase.objects.filter(
        tipo='COLEGIO', registrado_por__isnull=True
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('colegios', '0018_cancelacionclase'),
    ]

    operations = [
        migrations.RunPython(backfill_cancelaciones, revertir_backfill),
    ]
