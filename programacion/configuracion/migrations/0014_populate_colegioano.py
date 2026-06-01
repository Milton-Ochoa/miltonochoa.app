"""
Data migration: Crea registros ColegioAño a partir de los Colegio existentes.

Estrategia:
1. Para cada Colegio existente, crear un ColegioAño con el MISMO ID.
2. Agrupar colegios por nombre; elegir uno como "permanente" (el de menor ID).
3. Para los duplicados: redirigir UsuarioColegio al permanente, luego eliminar.
4. Los FKs de Bloque/Clase/Asignacion/etc. ya apuntan al ID correcto
   porque ColegioAño.id == Colegio.id original.
"""

from django.db import migrations


def poblar_colegioano(apps, schema_editor):
    Colegio     = apps.get_model('configuracion', 'Colegio')
    ColegioAño  = apps.get_model('configuracion', 'ColegioAño')

    # Importar modelos que necesitan reasignación
    try:
        UsuarioColegio = apps.get_model('usuarios', 'UsuarioColegio')
    except LookupError:
        UsuarioColegio = None

    # Paso 1: Crear ColegioAño para cada Colegio existente (mismo ID)
    colegios_all = list(Colegio.objects.all().order_by('id'))
    for col in colegios_all:
        ColegioAño.objects.create(
            id=col.id,
            colegio_id=col.id,  # temporalmente apunta a sí mismo
            año=col.año,
            activo=col.activo,
        )

    # Paso 2: Agrupar por nombre y fusionar
    from collections import defaultdict
    grupos = defaultdict(list)
    for col in colegios_all:
        grupos[col.nombre].append(col)

    for nombre, colegios in grupos.items():
        if len(colegios) <= 1:
            continue

        # El permanente es el de menor ID
        permanente = colegios[0]

        for col in colegios[1:]:
            # Reasignar ColegioAño para que apunte al permanente
            ColegioAño.objects.filter(id=col.id).update(colegio_id=permanente.id)

            # Reasignar UsuarioColegio
            if UsuarioColegio:
                UsuarioColegio.objects.filter(colegio_id=col.id).update(
                    colegio_id=permanente.id
                )

            # Copiar datos más recientes al permanente (dirección, etc.)
            permanente.codigo = col.codigo or permanente.codigo
            permanente.departamento = col.departamento or permanente.departamento
            permanente.ciudad = col.ciudad or permanente.ciudad
            permanente.direccion = col.direccion or permanente.direccion
            permanente.observacion = col.observacion or permanente.observacion
            permanente.mapa_link = col.mapa_link or permanente.mapa_link

        permanente.save()

        # Eliminar duplicados (ya redirigimos todo)
        for col in colegios[1:]:
            col.delete()

    # Resetear secuencia de ColegioAño para evitar conflictos
    db_alias = schema_editor.connection.alias
    if schema_editor.connection.vendor == 'postgresql':
        # Obtenemos el ID máximo actual
        max_id = ColegioAño.objects.order_by('-id').values_list('id', flat=True).first()
        
        # Solo ejecutamos setval si existe al menos un registro (max_id no es None)
        if max_id:
            schema_editor.execute(
                f"SELECT setval(pg_get_serial_sequence('configuracion_colegioaño', 'id'), %s, true)",
                [max_id]
            )
        else:
            # Si la tabla está vacía, reiniciamos la secuencia al inicio (1)
            schema_editor.execute(
                f"ALTER SEQUENCE configuracion_colegioaño_id_seq RESTART WITH 1"
            )


def reverse_migration(apps, schema_editor):
    ColegioAño = apps.get_model('configuracion', 'ColegioAño')
    ColegioAño.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('configuracion', '0013_colegioano_model'),
        ('usuarios', '0002_alter_usuariocolegio_password_texto_and_more'),
    ]

    operations = [
        migrations.RunPython(poblar_colegioano, reverse_migration),
    ]
