"""Validación de los adjuntos de entradas (facturas/remisiones).

Mismas reglas que los soportes de pago (`programacion.viaticos.soportes`):
extensión permitida y tamaño máximo. Se duplica aquí a propósito — el
inventario no debe importar de programación; cada dominio es dueño de sus
reglas aunque hoy coincidan.
"""
import os

ADJUNTO_EXTENSIONES = {'.pdf', '.jpg', '.jpeg', '.png'}
ADJUNTO_MAX_BYTES = 10 * 1024 * 1024  # 10 MB


def validar_adjunto(archivo):
    """Valida extensión y tamaño de un adjunto; devuelve un mensaje de error o None."""
    ext = os.path.splitext(archivo.name)[1].lower()
    if ext not in ADJUNTO_EXTENSIONES:
        return f'Tipo de archivo no permitido ({ext or "sin extensión"}). Usa PDF, JPG o PNG.'
    if archivo.size > ADJUNTO_MAX_BYTES:
        return 'El archivo supera el tamaño máximo de 10 MB.'
    return None
