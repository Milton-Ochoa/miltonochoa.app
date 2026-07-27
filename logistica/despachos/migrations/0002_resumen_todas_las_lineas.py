"""El resumen de artículos pasa a incluir TODAS las líneas (también FORMACIÓN).

Además de ampliar el campo, recalcula el resumen de las órdenes ya importadas:
sin este backfill las órdenes viejas seguirían mostrando solo su material hasta
la siguiente carga del reporte, y las 100% FORMACIÓN (que ahora sí aparecen en
el tablero) se verían sin artículos.
"""
from decimal import Decimal

from django.db import migrations, models

_MAX_RESUMEN = 500


def _cant_str(cantidad):
    """Decimal → texto compacto ('17.00' → '17'). Reimplementado aquí a
    propósito: una migración no debe importar de `services.py`, que evoluciona."""
    c = Decimal(cantidad)
    if c == c.to_integral_value():
        return str(int(c))
    return format(c.normalize(), 'f')


def _recalcular_resumenes(apps, schema_editor):
    OrdenDespacho = apps.get_model('log_despachos', 'OrdenDespacho')
    LineaOrden = apps.get_model('log_despachos', 'LineaOrden')

    partes_por_orden = {}
    lineas = (LineaOrden.objects.filter(eliminada_erp=False)
              .order_by('orden_archivo', 'id')
              .values_list('orden_id', 'cantidad', 'descripcion', 'cod_articulo'))
    for orden_id, cantidad, descripcion, cod_articulo in lineas.iterator():
        partes_por_orden.setdefault(orden_id, []).append(
            f'{_cant_str(cantidad)}× {descripcion or cod_articulo}')

    actualizar = []
    for orden in OrdenDespacho.objects.only('id', 'resumen_articulos').iterator():
        resumen = ''
        for parte in partes_por_orden.get(orden.id, ()):
            candidato = f'{resumen}; {parte}' if resumen else parte
            if len(candidato) > _MAX_RESUMEN:
                break
            resumen = candidato
        if resumen != orden.resumen_articulos:
            orden.resumen_articulos = resumen
            actualizar.append(orden)
        if len(actualizar) >= 500:
            OrdenDespacho.objects.bulk_update(actualizar, ['resumen_articulos'])
            actualizar = []
    if actualizar:
        OrdenDespacho.objects.bulk_update(actualizar, ['resumen_articulos'])


class Migration(migrations.Migration):

    dependencies = [
        ('log_despachos', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='ordendespacho',
            name='resumen_articulos',
            field=models.CharField(blank=True, max_length=500),
        ),
        # Reverse noop: volver a 300 truncaría igual y el resumen se regenera en
        # la siguiente carga del reporte.
        migrations.RunPython(_recalcular_resumenes, migrations.RunPython.noop),
    ]
