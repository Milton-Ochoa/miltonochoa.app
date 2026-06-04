"""Saca `PagoRealizado`/`SoportePagoProfesor` del *state* de la app `exportar`.

Los modelos se mudan a la app `pagos` (sub-app propia). Esta migración los elimina
**solo del state** con `SeparateDatabaseAndState` y `database_operations` vacías: las
tablas `prog_pagos`/`prog_pagos_soportes` permanecen en la BD (no hay DROP). La
recreación en el state de `pagos` ocurre en `pagos.0001_initial`, que depende de esta.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('exportar', '0003_soportepagoprofesor'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name='SoportePagoProfesor'),
                migrations.DeleteModel(name='PagoRealizado'),
            ],
            database_operations=[],
        ),
    ]
