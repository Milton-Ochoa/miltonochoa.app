"""Movimiento de modelos `exportar` → `pagos` (sub-app propia).

Los modelos `PagoRealizado` y `SoportePagoProfesor` (tablas `prog_pagos` y
`prog_pagos_soportes`) se extraen de la app `exportar` a su nueva app `pagos`.
Como las tablas **ya existen** (datos en producción), esta migración solo registra
los modelos en el *state* de Django con `SeparateDatabaseAndState` y `database_operations`
vacías: **no ejecuta DDL**, así los datos se conservan intactos. La eliminación del
state previo (en `exportar`) ocurre en `exportar.0004_remove_pagos`, de la que depende.
"""
import django.db.models.deletion
import programacion.pagos.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('configuracion', '0022_alter_materia_color'),
        ('exportar', '0004_remove_pagos'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='PagoRealizado',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('fecha', models.DateField(verbose_name='Fecha de la clase')),
                        ('horas', models.FloatField(verbose_name='Horas dictadas')),
                        ('valor', models.IntegerField(verbose_name='Valor pagado (COP)')),
                        ('fecha_pago', models.DateTimeField(auto_now_add=True, verbose_name='Fecha de pago')),
                        ('colegio', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='pagos_realizados', to='configuracion.colegioanio', verbose_name='Colegio/Año')),
                        ('marcado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='pagos_marcados', to=settings.AUTH_USER_MODEL, verbose_name='Marcado por')),
                        ('profesor', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='pagos_realizados', to='configuracion.profesor', verbose_name='Profesor')),
                    ],
                    options={
                        'verbose_name': 'Pago Realizado',
                        'verbose_name_plural': 'Pagos Realizados',
                        'db_table': 'prog_pagos',
                        'ordering': ['-fecha', 'profesor__nombre'],
                        'unique_together': {('profesor', 'colegio', 'fecha')},
                    },
                ),
                migrations.CreateModel(
                    name='SoportePagoProfesor',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('archivo', models.FileField(upload_to=programacion.pagos.models._pago_soporte_upload_to)),
                        ('nombre_original', models.CharField(blank=True, max_length=255)),
                        ('subido_en', models.DateTimeField(auto_now_add=True)),
                        ('pago', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='soportes', to='pagos.pagorealizado')),
                        ('subido_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='soportes_pago', to=settings.AUTH_USER_MODEL)),
                    ],
                    options={
                        'verbose_name': 'Soporte de pago a profesor',
                        'verbose_name_plural': 'Soportes de pago a profesor',
                        'db_table': 'prog_pagos_soportes',
                        'ordering': ['-subido_en'],
                    },
                ),
            ],
            database_operations=[],
        ),
    ]
