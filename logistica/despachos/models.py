"""Modelos de la sub-app de despachos de material (logística).

Espejo local de las órdenes de venta del ERP externo. El ERP es la fuente de
verdad de los datos de orden (cliente, bodega, fechas, estados de facturación);
AAMO añade una capa de **trabajo local**: estado de alistamiento/despacho,
cambios de material y verificación cruzada. Los campos ERP SOLO los escribe el
import (`services.py`, F2); las marcas locales JAMÁS se pisan desde el archivo.

Convención del proyecto: label 'log_despachos' (ruta de import ≠ app_label) y
tablas con prefijo 'log_'. El `EventoOrden` es **append-only** (patrón del ledger
`Movimiento` del inventario): nunca se edita ni se borra.
"""
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class CargaReporte(models.Model):
    """Metadata de cada importación del reporte ERP (no guarda el archivo, solo
    los contadores del resultado). Sirve de bitácora y de ancla del anti-viejo
    (se compara `max_fecha_orden` contra la última carga)."""

    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                blank=True, related_name='cargas_despachos')
    nombre_archivo = models.CharField(max_length=255, blank=True)
    # Máxima 'Fecha orden' vista en el archivo: el anti-archivo-viejo rechaza una
    # carga cuyo max sea ESTRICTAMENTE menor que el de la última carga.
    max_fecha_orden = models.DateTimeField(null=True, blank=True)

    n_filas = models.PositiveIntegerField(default=0)
    n_ordenes = models.PositiveIntegerField(default=0)
    n_nuevas = models.PositiveIntegerField(default=0)
    n_actualizadas = models.PositiveIntegerField(default=0)
    n_cerradas_auto = models.PositiveIntegerField(default=0)
    n_alertas_remision = models.PositiveIntegerField(default=0)
    n_descartadas = models.PositiveIntegerField(default=0)

    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'log_despachos_cargas'
        ordering = ['-creado_en']
        verbose_name = 'Carga de reporte'
        verbose_name_plural = 'Cargas de reporte'

    def __str__(self):
        return f'Carga #{self.pk} — {self.creado_en:%Y-%m-%d %H:%M}'


class ArticuloERP(models.Model):
    """Catálogo de artículos del ERP, alimentado por los reportes (upsert por
    `codigo`). No es el `Item` del inventario: son códigos del ERP externo
    (SIM-*, MP*, HORAS CLASE…). Sirve de origen para el select de cambio de
    material."""

    codigo = models.CharField(max_length=60, unique=True)
    descripcion = models.CharField(max_length=300, blank=True)
    # Texto ERP tal cual (EVALUACIÓN / FORMACIÓN / …). La lógica de "es material"
    # vive en la línea (categoria ≠ FORMACIÓN).
    categoria = models.CharField(max_length=100, blank=True, db_index=True)

    class Meta:
        db_table = 'log_despachos_articulos'
        ordering = ['codigo']
        verbose_name = 'Artículo ERP'
        verbose_name_plural = 'Artículos ERP'

    def __str__(self):
        return f'{self.codigo} — {self.descripcion}' if self.descripcion else self.codigo


class OrdenDespacho(models.Model):
    """Una orden de venta del ERP (identificada por `id_orden` = PPAL-N). Los
    atributos ERP son idénticos en todas las líneas de la misma orden en el
    reporte (verificado sobre el archivo real), así que se materializan aquí una
    sola vez; las líneas cuelgan en `LineaOrden`."""

    # Categoría del ERP que NO es material (no entra al tablero de despachos).
    CATEGORIA_FORMACION = 'FORMACION'

    class Estado(models.TextChoices):
        PENDIENTE = 'PENDIENTE', 'Pendiente'
        ALISTADA = 'ALISTADA', 'Alistada'
        DESPACHADA = 'DESPACHADA', 'Despachada'
        # Terminales automáticos del import (orden anulada en el ERP):
        REMITIDA = 'REMITIDA', 'Remitida (cerrada en ERP)'
        ANULADA = 'ANULADA', 'Anulada'

    # Estados en los que la orden sigue "viva" (aparece en el tablero de trabajo).
    ESTADOS_ABIERTOS = {Estado.PENDIENTE, Estado.ALISTADA}
    ESTADOS_TERMINALES = {Estado.REMITIDA, Estado.ANULADA}

    id_orden = models.CharField(max_length=30, unique=True)

    # --- Espejo ERP (solo lo escribe el import) ------------------------------
    sucursal = models.CharField(max_length=120, blank=True)
    centro_costos = models.CharField(max_length=120, blank=True)
    bodega = models.CharField(max_length=120, blank=True, db_index=True)
    estado_orden_erp = models.CharField(max_length=120, blank=True)
    estado_facturacion = models.CharField(max_length=200, blank=True)
    vigencia = models.CharField(max_length=60, blank=True)
    cliente = models.CharField(max_length=200, blank=True)
    id_cliente = models.CharField(max_length=60, blank=True)
    telefono = models.CharField(max_length=60, blank=True)
    departamento = models.CharField(max_length=120, blank=True)
    ciudad = models.CharField(max_length=120, blank=True)
    direccion = models.CharField(max_length=250, blank=True)
    vendedor = models.CharField(max_length=200, blank=True)
    observacion = models.TextField(blank=True)
    fecha_entrega = models.DateField(null=True, blank=True)
    fecha_orden = models.DateTimeField(null=True, blank=True)

    # --- Estado local de trabajo (JAMÁS se pisa desde el archivo) ------------
    estado = models.CharField(max_length=12, choices=Estado.choices,
                              default=Estado.PENDIENTE)
    alistada_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                     blank=True, related_name='ordenes_alistadas')
    alistada_en = models.DateTimeField(null=True, blank=True)
    despachada_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                       blank=True, related_name='ordenes_despachadas')
    despachada_en = models.DateTimeField(null=True, blank=True)
    cerrada_en = models.DateTimeField(null=True, blank=True)
    # Se cerró en el ERP (anulada) sin que aquí se marcara despacho → revisar.
    cerrada_sin_marcar = models.BooleanField(default=False)
    # Despachada aquí pero el ERP sigue vigente+pendiente (falta la remisión).
    alerta_remision = models.BooleanField(default=False)

    # --- Denormalizaciones del import (para tablero/alertas sin joins) -------
    # ≥1 línea EVALUACIÓN (material). Una orden 100% FORMACIÓN no es despachable.
    es_despachable = models.BooleanField(default=True)
    n_lineas = models.PositiveIntegerField(default=0)  # solo material
    resumen_articulos = models.CharField(max_length=300, blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'log_despachos_ordenes'
        ordering = ['fecha_entrega', 'id_orden']
        verbose_name = 'Orden de despacho'
        verbose_name_plural = 'Órdenes de despacho'
        indexes = [
            # Badge de vencidas, alertas y las tabs del tablero.
            models.Index(fields=['estado', 'fecha_entrega']),
        ]

    def __str__(self):
        return f'{self.id_orden} — {self.cliente}'

    @property
    def abierta(self):
        return self.estado in self.ESTADOS_ABIERTOS

    @property
    def terminal(self):
        """Cerrada en el ERP (REMITIDA/ANULADA): no admite acciones locales."""
        return self.estado in self.ESTADOS_TERMINALES

    @property
    def vencida(self):
        """Abierta, despachable y con fecha de entrega ya pasada."""
        return (self.abierta and self.es_despachable and self.fecha_entrega
                and self.fecha_entrega < timezone.localdate())


class LineaOrden(models.Model):
    """Un artículo de una orden (una fila del reporte). Guarda snapshots del
    ERP + el cambio de material local (si lo hay)."""

    orden = models.ForeignKey(OrdenDespacho, on_delete=models.CASCADE,
                              related_name='lineas')
    articulo = models.ForeignKey(ArticuloERP, on_delete=models.PROTECT, null=True,
                                 blank=True, related_name='lineas')
    # Snapshots del ERP (sobreviven a cambios del catálogo).
    cod_articulo = models.CharField(max_length=60, blank=True)
    descripcion = models.CharField(max_length=300, blank=True)
    categoria = models.CharField(max_length=100, blank=True)
    cantidad = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # categoria ≠ FORMACIÓN → material que se despacha físicamente.
    es_material = models.BooleanField(default=True)
    # Ordinal de la línea dentro del archivo: desempata artículos duplicados en
    # la misma orden al re-sincronizar (n-ésima con n-ésima).
    orden_archivo = models.PositiveIntegerField(default=0)

    # --- Cambio de material (local) ------------------------------------------
    articulo_cambio = models.ForeignKey(ArticuloERP, on_delete=models.PROTECT,
                                        null=True, blank=True,
                                        related_name='lineas_como_cambio')
    cantidad_cambio = models.DecimalField(max_digits=10, decimal_places=2,
                                          null=True, blank=True)
    cambiado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                     blank=True, related_name='lineas_cambiadas')
    cambiado_en = models.DateTimeField(null=True, blank=True)
    # El cambio se hizo aquí pero falta reflejarlo en el ERP (se desmarca a mano).
    pendiente_erp = models.BooleanField(default=False)
    # El ERP borró esta línea por debajo, pero tenía cambio de material marcado
    # → se conserva como rastro en vez de borrarla.
    eliminada_erp = models.BooleanField(default=False)

    class Meta:
        db_table = 'log_despachos_lineas'
        ordering = ['orden_archivo', 'id']
        verbose_name = 'Línea de orden'
        verbose_name_plural = 'Líneas de orden'
        indexes = [
            models.Index(fields=['orden', 'cod_articulo']),
        ]

    def __str__(self):
        return f'{self.cantidad} × {self.cod_articulo} ({self.orden.id_orden})'

    @property
    def tiene_cambio(self):
        return self.articulo_cambio_id is not None


class AsignacionBodega(models.Model):
    """Bodega ERP por defecto de un usuario (BUCARAMANGA, B.BARRANQUILLA,
    MONTERIA — texto ERP). Fija el filtro inicial del tablero; el usuario puede
    quitarlo para ver todo. La gestiona SOLO el superusuario."""

    usuario = models.OneToOneField(User, on_delete=models.CASCADE,
                                   related_name='bodega_despachos')
    bodega = models.CharField(max_length=120)
    asignado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                     blank=True, related_name='bodegas_asignadas')
    asignado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'log_despachos_bodegas_usuarios'
        ordering = ['usuario__username']
        verbose_name = 'Asignación de bodega'
        verbose_name_plural = 'Asignaciones de bodega'

    def __str__(self):
        return f'{self.usuario} → {self.bodega}'


class EventoOrden(models.Model):
    """Bitácora append-only de una orden (patrón del ledger `Movimiento`): nunca
    se edita ni se borra. Registra transiciones de estado, cierres automáticos,
    alertas y cambios de material — con usuario (None = automático del import)."""

    class Tipo(models.TextChoices):
        ALISTADA = 'ALISTADA', 'Alistada'
        DESPACHADA = 'DESPACHADA', 'Despachada'
        REVERTIDA = 'REVERTIDA', 'Revertida'
        CIERRE_AUTO = 'CIERRE_AUTO', 'Cierre automático (despachada)'
        CIERRE_SIN_MARCAR = 'CIERRE_SIN_MARCAR', 'Cerrada en ERP sin marcar'
        ALERTA_REMISION = 'ALERTA_REMISION', 'Despachada sin remisión'
        CAMBIO_MATERIAL = 'CAMBIO_MATERIAL', 'Cambio de material'
        CAMBIO_REVERTIDO = 'CAMBIO_REVERTIDO', 'Cambio de material revertido'
        ERP_ACTUALIZADO = 'ERP_ACTUALIZADO', 'Cambio actualizado en ERP'
        LINEA_HUERFANA = 'LINEA_HUERFANA', 'Línea con cambio eliminada en ERP'

    orden = models.ForeignKey(OrdenDespacho, on_delete=models.CASCADE,
                              related_name='eventos')
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    detalle = models.CharField(max_length=300, blank=True)
    # None = evento automático (generado por el import), sin usuario humano.
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                blank=True, related_name='eventos_despachos')
    carga = models.ForeignKey(CargaReporte, on_delete=models.SET_NULL, null=True,
                              blank=True, related_name='eventos')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'log_despachos_eventos'
        ordering = ['-creado_en', '-id']
        verbose_name = 'Evento de orden'
        verbose_name_plural = 'Eventos de orden'
        indexes = [
            models.Index(fields=['orden', 'creado_en']),
        ]

    def __str__(self):
        return f'{self.get_tipo_display()} — {self.orden_id}'
