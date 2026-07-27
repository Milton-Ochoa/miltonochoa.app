import os

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


# ---------------------------------------------------------------------------
# Catálogos
# ---------------------------------------------------------------------------

class Categoria(models.Model):
    nombre = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = 'log_categorias'
        ordering = ['nombre']
        verbose_name = 'Categoría'
        verbose_name_plural = 'Categorías'

    def __str__(self):
        return self.nombre


class Bodega(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    ubicacion = models.CharField(max_length=200, blank=True)
    # Soft-delete: las bodegas referenciadas por el ledger no se borran. El guard
    # "no desactivar con stock > 0" lo aplica la vista (Fase 3), no el modelo.
    activa = models.BooleanField(default=True)

    class Meta:
        db_table = 'log_bodegas'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


# Grados escolares del material: 0° (transición) a 11°. Todo material existe
# en los 12 grados — no hay material "sin grado".
GRADO_MIN, GRADO_MAX = 0, 11
GRADOS = tuple(range(GRADO_MIN, GRADO_MAX + 1))


class Item(models.Model):
    """Unidad de inventario: un material en UN grado. Todo se maneja por
    cantidad (sin seriales).

    El "material" (lo que el usuario reconoce como artículo) NO tiene tabla
    propia: es la pareja **(categoría = modelo del material, referencia)**
    repetida en los 12 grados. Por eso el alta crea siempre el juego completo
    y los campos compartidos (unidad, descripción, mínimo, valor, activo) se
    editan en grupo desde la UI. El grado vive aquí —y no en un modelo hijo—
    porque es lo que se mueve: stock, kardex y documentos son por grado.
    """

    class UnidadMedida(models.TextChoices):
        UNIDAD  = 'UNIDAD',  'Unidad'
        PAQUETE = 'PAQUETE', 'Paquete'
        CAJA    = 'CAJA',    'Caja'
        RESMA   = 'RESMA',   'Resma'

    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT,
                                  related_name='items')
    # Variante dentro de la categoría (p. ej. "Cuadernillo A"). Puede ir vacía:
    # hay categorías con un único material y sin referencia interna.
    referencia = models.CharField(max_length=100, blank=True, default='')
    grado = models.PositiveSmallIntegerField()
    unidad_medida = models.CharField(max_length=10, choices=UnidadMedida.choices,
                                     default=UnidadMedida.UNIDAD)
    descripcion = models.TextField(blank=True)
    # 0 = sin alerta. El mínimo es GLOBAL (suma de todas las bodegas); por-bodega
    # quedó como refinamiento futuro.
    stock_minimo = models.PositiveIntegerField(default=0)
    # COP, referencial para exports. El kardex es de cantidades, no de costos
    # (sin FIFO/promedio).
    valor_unitario = models.PositiveIntegerField(null=True, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = 'log_articulos'
        ordering = ['categoria__nombre', 'referencia', 'grado']
        verbose_name = 'Artículo'
        constraints = [
            models.UniqueConstraint(fields=['categoria', 'referencia', 'grado'],
                                    name='unique_item_material_grado'),
            # PositiveSmallIntegerField ya impide negativos; falta el techo.
            models.CheckConstraint(condition=models.Q(grado__lte=GRADO_MAX),
                                   name='item_grado_valido'),
        ]

    def __str__(self):
        return self.nombre

    @property
    def material(self):
        """Nombre del material SIN el grado: la fila que ve el usuario."""
        return f'{self.categoria.nombre} {self.referencia}'.strip()

    @property
    def nombre(self):
        """Etiqueta completa (material + grado). Derivada, ya no es campo: el
        ledger, los mensajes de dominio y las plantillas la siguen usando."""
        return f'{self.material} — {self.grado_display}'

    @property
    def grado_display(self):
        return f'{self.grado}°'

    @property
    def clave_material(self):
        """Identifica al MATERIAL (no a esta fila) en los formularios; la
        deshace `forms.parsear_clave_material`."""
        return f'{self.categoria_id}:{self.referencia}'


class Tercero(models.Model):
    """Destinatario/origen externo de salidas y préstamos (catálogo ligero,
    creable al vuelo). NO es FK a Profesor/Colegio a propósito: los documentos
    guardan además snapshot de texto para sobrevivir borrados."""

    nombre = models.CharField(max_length=200)
    documento = models.CharField(max_length=50, blank=True)
    telefono = models.CharField(max_length=50, blank=True)
    notas = models.TextField(blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = 'log_terceros'
        ordering = ['nombre']
        constraints = [
            # Documento único solo cuando se diligencia (vacío se repite libre).
            models.UniqueConstraint(fields=['documento'],
                                    condition=~models.Q(documento=''),
                                    name='unique_tercero_documento'),
        ]

    def __str__(self):
        return f'{self.nombre} ({self.documento})' if self.documento else self.nombre


# ---------------------------------------------------------------------------
# Stock denormalizado
# ---------------------------------------------------------------------------

class Stock(models.Model):
    """Existencia actual de un item en una bodega. SOLO lo escriben los
    servicios de dominio (services.py), bajo lock y en la misma transacción
    que el Movimiento; las vistas jamás lo tocan directo."""

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='stocks')
    bodega = models.ForeignKey(Bodega, on_delete=models.PROTECT, related_name='stocks')
    # PositiveIntegerField ⇒ CHECK >= 0 en BD: última barrera contra negativos
    # incluso si una carrera burlara la validación de los servicios.
    cantidad = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'log_stock'
        constraints = [
            models.UniqueConstraint(fields=['item', 'bodega'],
                                    name='unique_stock_item_bodega'),
        ]
        verbose_name_plural = 'Stocks'

    def __str__(self):
        return f'{self.item} @ {self.bodega}: {self.cantidad}'


# ---------------------------------------------------------------------------
# Ledger (kardex) — append-only: los errores se corrigen con un
# contramovimiento/ajuste, NUNCA editando o borrando filas. Sin vistas de
# edición/borrado jamás.
# ---------------------------------------------------------------------------

class Movimiento(models.Model):
    class Tipo(models.TextChoices):
        ENTRADA        = 'ENTRADA',        'Entrada'
        SALIDA         = 'SALIDA',         'Salida'
        PRESTAMO       = 'PRESTAMO',       'Préstamo otorgado'
        DEVOLUCION     = 'DEVOLUCION',     'Devolución de préstamo otorgado'
        PREST_RECIBIDO = 'PREST_RECIBIDO', 'Préstamo recibido'
        DEV_RECIBIDO   = 'DEV_RECIBIDO',   'Devolución de préstamo recibido'
        TRASLADO_SAL   = 'TRASLADO_SAL',   'Traslado (salida)'
        TRASLADO_ENT   = 'TRASLADO_ENT',   'Traslado (entrada)'
        AJUSTE_POS     = 'AJUSTE_POS',     'Ajuste positivo'
        AJUSTE_NEG     = 'AJUSTE_NEG',     'Ajuste negativo'

    # Tipos que SUMAN stock; el resto resta. El signo lo da el tipo: `cantidad`
    # siempre es > 0.
    TIPOS_POSITIVOS = {Tipo.ENTRADA, Tipo.DEVOLUCION, Tipo.PREST_RECIBIDO,
                       Tipo.TRASLADO_ENT, Tipo.AJUSTE_POS}

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='movimientos')
    bodega = models.ForeignKey(Bodega, on_delete=models.PROTECT, related_name='movimientos')
    tipo = models.CharField(max_length=15, choices=Tipo.choices)
    cantidad = models.PositiveIntegerField()
    # Saldo de item×bodega TRAS aplicar este movimiento, calculado bajo lock:
    # da un kardex con saldo por fila sin window functions.
    saldo_resultante = models.PositiveIntegerField()

    # Documento de origen (uno solo por movimiento; el resto queda en NULL).
    # PROTECT: el ledger impide borrar los documentos que ya movieron stock.
    entrada = models.ForeignKey('Entrada', on_delete=models.PROTECT, null=True,
                                blank=True, related_name='movimientos')
    salida = models.ForeignKey('Salida', on_delete=models.PROTECT, null=True,
                               blank=True, related_name='movimientos')
    prestamo = models.ForeignKey('Prestamo', on_delete=models.PROTECT, null=True,
                                 blank=True, related_name='movimientos')
    devolucion = models.ForeignKey('Devolucion', on_delete=models.PROTECT, null=True,
                                   blank=True, related_name='movimientos')
    traslado = models.ForeignKey('Traslado', on_delete=models.PROTECT, null=True,
                                 blank=True, related_name='movimientos')

    # Snapshot legible del contexto (proveedor, tercero, motivo…): el ledger se
    # entiende solo, sin abrir el documento.
    detalle = models.CharField(max_length=250, blank=True)

    creado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name='movimientos_inventario')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'log_movimientos'
        ordering = ['-creado_en', '-id']
        constraints = [
            models.CheckConstraint(condition=models.Q(cantidad__gt=0),
                                   name='movimiento_cantidad_positiva'),
        ]
        indexes = [
            models.Index(fields=['item', 'bodega', 'creado_en']),
            models.Index(fields=['item', 'creado_en']),
            models.Index(fields=['tipo', 'creado_en']),
        ]

    def __str__(self):
        return f'{self.get_tipo_display()} {self.cantidad} × {self.item} @ {self.bodega}'

    @property
    def delta(self):
        """Efecto del movimiento sobre el stock: ±cantidad según el tipo."""
        return self.cantidad if self.tipo in self.TIPOS_POSITIVOS else -self.cantidad


# ---------------------------------------------------------------------------
# Documentos (cabecera + líneas)
# ---------------------------------------------------------------------------

class Entrada(models.Model):
    bodega = models.ForeignKey(Bodega, on_delete=models.PROTECT, related_name='entradas')
    proveedor = models.CharField(max_length=200, blank=True)
    observaciones = models.TextField(blank=True)
    creado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name='entradas_inventario')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'log_entradas'
        ordering = ['-creado_en']

    def __str__(self):
        return f'Entrada #{self.pk} — {self.bodega}'


class EntradaLinea(models.Model):
    entrada = models.ForeignKey(Entrada, on_delete=models.CASCADE, related_name='lineas')
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='+')
    cantidad = models.PositiveIntegerField()

    class Meta:
        db_table = 'log_entradas_lineas'
        constraints = [
            models.CheckConstraint(condition=models.Q(cantidad__gt=0),
                                   name='entrada_linea_cantidad_positiva'),
        ]

    def __str__(self):
        return f'{self.cantidad} × {self.item}'


def _adjunto_entrada_upload_to(instance, filename):
    """``logistica/entradas/entrada-<id>-<slug><ext>`` (patrón SoportePago:
    nombre legible y estable; el storage añade sufijo único si se repite)."""
    base, ext = os.path.splitext(filename)
    slug = slugify(base) or 'adjunto'
    return f'logistica/entradas/entrada-{instance.entrada_id}-{slug}{ext.lower()}'


class AdjuntoEntrada(models.Model):
    """Factura/remisión adjunta a una entrada (varios por documento, con
    historial de quién subió qué y cuándo)."""

    entrada = models.ForeignKey(Entrada, on_delete=models.CASCADE, related_name='adjuntos')
    archivo = models.FileField(upload_to=_adjunto_entrada_upload_to)
    nombre_original = models.CharField(max_length=255, blank=True)
    subido_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name='adjuntos_inventario')
    subido_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'log_entradas_adjuntos'
        ordering = ['-subido_en']

    def __str__(self):
        return f'Adjunto de entrada #{self.entrada_id} ({self.nombre_mostrar})'

    @property
    def nombre_mostrar(self):
        """Basename real en storage (refleja el renombrado del upload_to y el
        sufijo único), no el nombre original subido."""
        if self.archivo and self.archivo.name:
            return os.path.basename(self.archivo.name)
        return self.nombre_original or 'archivo'


class Salida(models.Model):
    bodega = models.ForeignKey(Bodega, on_delete=models.PROTECT, related_name='salidas')
    tercero = models.ForeignKey(Tercero, on_delete=models.SET_NULL, null=True,
                                blank=True, related_name='salidas')
    # Snapshot de texto (patrón CancelacionClase): el documento sobrevive al
    # borrado del tercero.
    tercero_nombre = models.CharField(max_length=200, blank=True)
    motivo = models.CharField(max_length=200, blank=True)
    observaciones = models.TextField(blank=True)
    creado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name='salidas_inventario')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'log_salidas'
        ordering = ['-creado_en']

    def __str__(self):
        return f'Salida #{self.pk} — {self.bodega}'


class SalidaLinea(models.Model):
    salida = models.ForeignKey(Salida, on_delete=models.CASCADE, related_name='lineas')
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='+')
    cantidad = models.PositiveIntegerField()

    class Meta:
        db_table = 'log_salidas_lineas'
        constraints = [
            models.CheckConstraint(condition=models.Q(cantidad__gt=0),
                                   name='salida_linea_cantidad_positiva'),
        ]

    def __str__(self):
        return f'{self.cantidad} × {self.item}'


class Traslado(models.Model):
    bodega_origen = models.ForeignKey(Bodega, on_delete=models.PROTECT,
                                      related_name='traslados_salientes')
    bodega_destino = models.ForeignKey(Bodega, on_delete=models.PROTECT,
                                       related_name='traslados_entrantes')
    observaciones = models.TextField(blank=True)
    creado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name='traslados_inventario')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'log_traslados'
        ordering = ['-creado_en']
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(bodega_origen=models.F('bodega_destino')),
                name='traslado_bodegas_distintas'),
        ]

    def __str__(self):
        return f'Traslado #{self.pk} — {self.bodega_origen} → {self.bodega_destino}'


class TrasladoLinea(models.Model):
    traslado = models.ForeignKey(Traslado, on_delete=models.CASCADE, related_name='lineas')
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='+')
    cantidad = models.PositiveIntegerField()

    class Meta:
        db_table = 'log_traslados_lineas'
        constraints = [
            models.CheckConstraint(condition=models.Q(cantidad__gt=0),
                                   name='traslado_linea_cantidad_positiva'),
        ]

    def __str__(self):
        return f'{self.cantidad} × {self.item}'


class Prestamo(models.Model):
    """Préstamo BIDIRECCIONAL: OTORGADO = nosotros prestamos a un tercero
    (descuenta stock al crear, lo restituye al devolver); RECIBIDO = un tercero
    NOS presta (suma stock al crear — entra al pool normal, distinguible en el
    kardex por el tipo —, y se descuenta al devolverlo). La validación de stock
    suficiente aplica en el lado negativo de cada dirección."""

    class Direccion(models.TextChoices):
        OTORGADO = 'OTORGADO', 'Prestamos nosotros'
        RECIBIDO = 'RECIBIDO', 'Nos prestan'

    class Estado(models.TextChoices):
        ABIERTO = 'ABIERTO', 'Abierto'
        PARCIAL = 'PARCIAL', 'Devuelto parcial'
        CERRADO = 'CERRADO', 'Cerrado'

    direccion = models.CharField(max_length=10, choices=Direccion.choices,
                                 default=Direccion.OTORGADO)
    # En RECIBIDO el tercero es quien NOS presta.
    tercero = models.ForeignKey(Tercero, on_delete=models.SET_NULL, null=True,
                                blank=True, related_name='prestamos')
    tercero_nombre = models.CharField(max_length=200)
    tercero_documento = models.CharField(max_length=50, blank=True)
    # En RECIBIDO: cuándo debemos devolver nosotros.
    fecha_compromiso = models.DateField()
    estado = models.CharField(max_length=10, choices=Estado.choices,
                              default=Estado.ABIERTO)
    cerrado_en = models.DateTimeField(null=True, blank=True)
    observaciones = models.TextField(blank=True)
    creado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name='prestamos_inventario')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'log_prestamos'
        ordering = ['-creado_en']
        indexes = [
            models.Index(fields=['estado', 'fecha_compromiso']),
        ]
        verbose_name = 'Préstamo'

    def __str__(self):
        return (f'Préstamo #{self.pk} ({self.get_direccion_display()}) — '
                f'{self.tercero_nombre}')

    @property
    def vencido(self):
        return (self.estado != self.Estado.CERRADO
                and self.fecha_compromiso < timezone.localdate())


class PrestamoLinea(models.Model):
    prestamo = models.ForeignKey(Prestamo, on_delete=models.CASCADE, related_name='lineas')
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='+')
    # La devolución opera SIEMPRE sobre la bodega de la línea (sin selector):
    # en OTORGADO el material vuelve aquí; en RECIBIDO sale de aquí.
    bodega = models.ForeignKey(Bodega, on_delete=models.PROTECT, related_name='+')
    cantidad_prestada = models.PositiveIntegerField()
    cantidad_devuelta = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'log_prestamos_lineas'
        constraints = [
            models.CheckConstraint(condition=models.Q(cantidad_prestada__gt=0),
                                   name='prestamo_linea_cantidad_positiva'),
            models.CheckConstraint(
                condition=models.Q(cantidad_devuelta__lte=models.F('cantidad_prestada')),
                name='prestamo_linea_devuelta_lte_prestada'),
        ]

    def __str__(self):
        return f'{self.cantidad_prestada} × {self.item} ({self.bodega})'

    @property
    def pendiente(self):
        return self.cantidad_prestada - self.cantidad_devuelta


class Devolucion(models.Model):
    """Acto de devolución (cabecera). Sin tabla de líneas: los `Movimiento`
    DEVOLUCION/DEV_RECIBIDO con FK `devolucion` SON las líneas."""

    prestamo = models.ForeignKey(Prestamo, on_delete=models.PROTECT,
                                 related_name='devoluciones')
    observaciones = models.TextField(blank=True)
    creado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name='devoluciones_inventario')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'log_prestamos_devoluciones'
        ordering = ['-creado_en']
        verbose_name = 'Devolución'
        verbose_name_plural = 'Devoluciones'

    def __str__(self):
        return f'Devolución #{self.pk} del préstamo #{self.prestamo_id}'
