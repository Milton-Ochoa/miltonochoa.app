"""Etapa de revisión de pagos en programación: lotes + desglose + lifecycle.

Añade el flujo "programación revisa y envía a financiera":
- `LotePagos` (tabla `prog_pagos_lotes`): estado semanal BORRADOR→ENVIADO.
- `ExtraPago` (tabla `prog_pagos_extras`): costos extra del desglose.
- `PagoRealizado` evoluciona: gana `lote`, `excluida`, `valor_base_editado`, y
  `fecha_pago` pasa a nullable (la fila ahora nace en BORRADOR sin estar pagada).

Las filas históricas de `prog_pagos` quedan normalizadas por los defaults de las
columnas nuevas (`lote=NULL`, `excluida=False`, `valor_base_editado=NULL`) y conservan
su `fecha_pago`; convención: `lote IS NULL AND fecha_pago IS NOT NULL` = histórico pagado.
No se crean lotes retroactivos.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pagos', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='pagorealizado',
            name='excluida',
            field=models.BooleanField(default=False, verbose_name='Excluida del envío'),
        ),
        migrations.AddField(
            model_name='pagorealizado',
            name='valor_base_editado',
            field=models.IntegerField(blank=True, null=True, verbose_name='Valor base editado (COP)'),
        ),
        migrations.AlterField(
            model_name='pagorealizado',
            name='fecha_pago',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Fecha de pago'),
        ),
        migrations.AlterField(
            model_name='pagorealizado',
            name='valor',
            field=models.IntegerField(verbose_name='Valor base calculado (COP)'),
        ),
        migrations.CreateModel(
            name='ExtraPago',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('concepto', models.CharField(max_length=200)),
                ('valor', models.PositiveIntegerField()),
                ('orden', models.PositiveSmallIntegerField(default=0)),
                ('pago', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='extras', to='pagos.pagorealizado')),
            ],
            options={
                'verbose_name': 'Costo extra de pago',
                'verbose_name_plural': 'Costos extra de pago',
                'db_table': 'prog_pagos_extras',
                'ordering': ['orden', 'id'],
            },
        ),
        migrations.CreateModel(
            name='LotePagos',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha_inicio', models.DateField(verbose_name='Inicio de la semana')),
                ('fecha_fin', models.DateField(verbose_name='Fin de la semana')),
                ('estado', models.CharField(choices=[('BORRADOR', 'Borrador'), ('ENVIADO', 'Enviado')], default='BORRADOR', max_length=10)),
                ('enviado_en', models.DateTimeField(blank=True, null=True)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('actualizado_en', models.DateTimeField(auto_now=True)),
                ('enviado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='lotes_pago_enviados', to=settings.AUTH_USER_MODEL, verbose_name='Enviado por')),
            ],
            options={
                'verbose_name': 'Lote de pagos',
                'verbose_name_plural': 'Lotes de pagos',
                'db_table': 'prog_pagos_lotes',
                'ordering': ['-fecha_inicio'],
                'unique_together': {('fecha_inicio', 'fecha_fin')},
            },
        ),
        migrations.AddField(
            model_name='pagorealizado',
            name='lote',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='filas', to='pagos.lotepagos', verbose_name='Lote'),
        ),
    ]
