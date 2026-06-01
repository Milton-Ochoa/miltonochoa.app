"""
Migración de normalización de base de datos.

Cambios:
- Asignacion.libro_titulo (CharField) → libro (FK a NombreLibro)
- Clase.materia (CharField) → materia (FK a Materia)
- ClaseParticular.materia (CharField) → materia (FK a Materia)
- ClaseParticular.grado (CharField) → grado (FK a Grado)
- ClaseParticular.hora (CharField) → hora_inicio + hora_fin (TimeField)
- HistorialCambio.objeto_id: IntegerField → BigIntegerField
- Indexes en Clase, HistorialCambio
- Clase.clean() validation (no migración necesaria)
"""
from datetime import time
from django.db import migrations, models
import django.db.models.deletion


def convertir_asignacion_libro(apps, schema_editor):
    """Poblar libro FK desde libro_titulo texto."""
    Asignacion = apps.get_model('colegios', 'Asignacion')
    NombreLibro = apps.get_model('configuracion', 'NombreLibro')

    titulos = set(Asignacion.objects.values_list('libro_titulo', flat=True))
    # Crear libros que no existan
    existentes = set(NombreLibro.objects.filter(nombre__in=titulos).values_list('nombre', flat=True))
    for titulo in titulos - existentes:
        if titulo and titulo.strip():
            NombreLibro.objects.create(nombre=titulo.strip(), activo=True)

    # Poblar FK
    for asig in Asignacion.objects.select_related().all():
        libro = NombreLibro.objects.filter(nombre=asig.libro_titulo).first()
        if libro:
            asig.libro_fk_id = libro.id
            asig.save(update_fields=['libro_fk_id'])


def convertir_clase_materia(apps, schema_editor):
    """Poblar materia FK desde materia texto en Clase."""
    Clase = apps.get_model('colegios', 'Clase')
    Materia = apps.get_model('configuracion', 'Materia')

    nombres = set(
        Clase.objects.exclude(materia_texto__isnull=True)
        .exclude(materia_texto='')
        .values_list('materia_texto', flat=True)
    )
    existentes = set(Materia.objects.filter(nombre__in=nombres).values_list('nombre', flat=True))
    for nombre in nombres - existentes:
        if nombre and nombre.strip():
            Materia.objects.create(nombre=nombre.strip())

    # Poblar FK
    mapa = {m.nombre: m.id for m in Materia.objects.all()}
    for clase in Clase.objects.exclude(materia_texto__isnull=True).exclude(materia_texto=''):
        mid = mapa.get(clase.materia_texto)
        if mid:
            Clase.objects.filter(pk=clase.pk).update(materia_fk_id=mid)


def convertir_particular_materia(apps, schema_editor):
    """Poblar materia FK desde materia texto en ClaseParticular."""
    CP = apps.get_model('colegios', 'ClaseParticular')
    Materia = apps.get_model('configuracion', 'Materia')

    nombres = set(CP.objects.values_list('materia_texto', flat=True))
    existentes = set(Materia.objects.filter(nombre__in=nombres).values_list('nombre', flat=True))
    for nombre in nombres - existentes:
        if nombre and nombre.strip():
            Materia.objects.create(nombre=nombre.strip())

    mapa = {m.nombre: m.id for m in Materia.objects.all()}
    for cp in CP.objects.all():
        mid = mapa.get(cp.materia_texto)
        if mid:
            CP.objects.filter(pk=cp.pk).update(materia_fk_id=mid)


def convertir_particular_grado(apps, schema_editor):
    """Poblar grado FK desde grado texto en ClaseParticular."""
    CP = apps.get_model('colegios', 'ClaseParticular')
    Grado = apps.get_model('colegios', 'Grado')

    nombres = set(CP.objects.values_list('grado_texto', flat=True))
    existentes = set(Grado.objects.filter(nombre__in=nombres).values_list('nombre', flat=True))
    for nombre in nombres - existentes:
        if nombre and nombre.strip():
            Grado.objects.create(nombre=nombre.strip())

    mapa = {g.nombre: g.id for g in Grado.objects.all()}
    for cp in CP.objects.all():
        gid = mapa.get(cp.grado_texto)
        if gid:
            CP.objects.filter(pk=cp.pk).update(grado_fk_id=gid)


def convertir_particular_hora(apps, schema_editor):
    """Convertir hora CharField '14:00 - 16:00' a hora_inicio/hora_fin TimeFields."""
    CP = apps.get_model('colegios', 'ClaseParticular')

    for cp in CP.objects.all():
        hora_str = cp.hora_texto or ''
        try:
            partes = hora_str.split('-')
            h1 = partes[0].strip().split(':')
            h2 = partes[1].strip().split(':')
            hi = time(int(h1[0]), int(h1[1]))
            hf = time(int(h2[0]), int(h2[1]))
        except (ValueError, IndexError):
            hi = time(8, 0)
            hf = time(10, 0)
        CP.objects.filter(pk=cp.pk).update(hora_inicio=hi, hora_fin=hf)


class Migration(migrations.Migration):

    atomic = False  # Necesario para PostgreSQL con múltiples ALTER + RunPython

    dependencies = [
        ('colegios', '0004_historial_cambio'),
        ('configuracion', '0010_materia_color'),
    ]

    operations = [
        # ══════════════════════════════════════════════════════════
        # 1. ASIGNACION: libro_titulo → libro FK
        # ══════════════════════════════════════════════════════════
        migrations.AddField(
            model_name='asignacion',
            name='libro_fk',
            field=models.ForeignKey(
                null=True, blank=True,
                on_delete=django.db.models.deletion.PROTECT,
                to='configuracion.nombrelibro',
                verbose_name='Libro',
            ),
        ),
        migrations.RunPython(convertir_asignacion_libro, migrations.RunPython.noop),
        migrations.RemoveField(model_name='asignacion', name='libro_titulo'),
        migrations.RenameField(
            model_name='asignacion',
            old_name='libro_fk',
            new_name='libro',
        ),
        migrations.AlterField(
            model_name='asignacion',
            name='libro',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                to='configuracion.nombrelibro',
                verbose_name='Libro',
            ),
        ),

        # ══════════════════════════════════════════════════════════
        # 2. CLASE: materia CharField → FK a Materia
        # ══════════════════════════════════════════════════════════
        migrations.RenameField(
            model_name='clase',
            old_name='materia',
            new_name='materia_texto',
        ),
        migrations.AddField(
            model_name='clase',
            name='materia_fk',
            field=models.ForeignKey(
                null=True, blank=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to='configuracion.materia',
            ),
        ),
        migrations.RunPython(convertir_clase_materia, migrations.RunPython.noop),
        migrations.RemoveField(model_name='clase', name='materia_texto'),
        migrations.RenameField(
            model_name='clase',
            old_name='materia_fk',
            new_name='materia',
        ),

        # ══════════════════════════════════════════════════════════
        # 3. CLASEPARTICULAR: materia CharField → FK a Materia
        # ══════════════════════════════════════════════════════════
        migrations.RenameField(
            model_name='claseparticular',
            old_name='materia',
            new_name='materia_texto',
        ),
        migrations.AddField(
            model_name='claseparticular',
            name='materia_fk',
            field=models.ForeignKey(
                null=True, blank=True,
                on_delete=django.db.models.deletion.PROTECT,
                to='configuracion.materia',
                verbose_name='Asignatura',
            ),
        ),
        migrations.RunPython(convertir_particular_materia, migrations.RunPython.noop),
        migrations.RemoveField(model_name='claseparticular', name='materia_texto'),
        migrations.RenameField(
            model_name='claseparticular',
            old_name='materia_fk',
            new_name='materia',
        ),
        migrations.AlterField(
            model_name='claseparticular',
            name='materia',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                to='configuracion.materia',
                verbose_name='Asignatura',
            ),
        ),

        # ══════════════════════════════════════════════════════════
        # 4. CLASEPARTICULAR: grado CharField → FK a Grado
        # ══════════════════════════════════════════════════════════
        migrations.RenameField(
            model_name='claseparticular',
            old_name='grado',
            new_name='grado_texto',
        ),
        migrations.AddField(
            model_name='claseparticular',
            name='grado_fk',
            field=models.ForeignKey(
                null=True, blank=True,
                on_delete=django.db.models.deletion.PROTECT,
                to='colegios.grado',
                verbose_name='Grado',
            ),
        ),
        migrations.RunPython(convertir_particular_grado, migrations.RunPython.noop),
        migrations.RemoveField(model_name='claseparticular', name='grado_texto'),
        migrations.RenameField(
            model_name='claseparticular',
            old_name='grado_fk',
            new_name='grado',
        ),
        migrations.AlterField(
            model_name='claseparticular',
            name='grado',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                to='colegios.grado',
                verbose_name='Grado',
            ),
        ),

        # ══════════════════════════════════════════════════════════
        # 5. CLASEPARTICULAR: hora CharField → hora_inicio + hora_fin
        # ══════════════════════════════════════════════════════════
        migrations.RenameField(
            model_name='claseparticular',
            old_name='hora',
            new_name='hora_texto',
        ),
        migrations.AddField(
            model_name='claseparticular',
            name='hora_inicio',
            field=models.TimeField(null=True, verbose_name='Hora de Inicio'),
        ),
        migrations.AddField(
            model_name='claseparticular',
            name='hora_fin',
            field=models.TimeField(null=True, verbose_name='Hora de Fin'),
        ),
        migrations.RunPython(convertir_particular_hora, migrations.RunPython.noop),
        migrations.RemoveField(model_name='claseparticular', name='hora_texto'),
        migrations.AlterField(
            model_name='claseparticular',
            name='hora_inicio',
            field=models.TimeField(verbose_name='Hora de Inicio'),
        ),
        migrations.AlterField(
            model_name='claseparticular',
            name='hora_fin',
            field=models.TimeField(verbose_name='Hora de Fin'),
        ),

        # ══════════════════════════════════════════════════════════
        # 6. HISTORIALCAMBIO: IntegerField → BigIntegerField + indexes
        # ══════════════════════════════════════════════════════════
        migrations.AlterField(
            model_name='historialcambio',
            name='objeto_id',
            field=models.BigIntegerField(),
        ),
        migrations.AddIndex(
            model_name='historialcambio',
            index=models.Index(fields=['objeto_tipo', 'objeto_id'],
                               name='colegios_hi_objeto__75aa6a_idx'),
        ),
        migrations.AddIndex(
            model_name='historialcambio',
            index=models.Index(fields=['colegio', 'fecha'],
                               name='colegios_hi_colegio_02309a_idx'),
        ),

        # ══════════════════════════════════════════════════════════
        # 7. CLASE: indexes
        # ══════════════════════════════════════════════════════════
        migrations.AddIndex(
            model_name='clase',
            index=models.Index(fields=['colegio', 'fecha'],
                               name='colegios_cl_colegio_68f439_idx'),
        ),
        migrations.AddIndex(
            model_name='clase',
            index=models.Index(fields=['fecha', 'cancelada'],
                               name='colegios_cl_fecha_2a4f59_idx'),
        ),
        migrations.AddIndex(
            model_name='clase',
            index=models.Index(fields=['profesor', 'fecha'],
                               name='colegios_cl_profeso_454e15_idx'),
        ),
    ]
