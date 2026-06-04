"""Validación común de los soportes de pago.

Mismas reglas (extensión permitida y tamaño máximo) para los dos flujos que adjuntan
comprobantes: viáticos (`financiera.viaticos`) y pagos a profesores (`financiera.pagos`).
Vive en `programacion.viaticos` para que ambas sub-apps de financiera lo compartan sin
acoplarse entre sí (mismo criterio con que importan modelos de programación).
"""
import os

SOPORTE_EXTENSIONES = {'.pdf', '.jpg', '.jpeg', '.png'}
SOPORTE_MAX_BYTES = 10 * 1024 * 1024  # 10 MB


def validar_soporte(archivo):
    """Valida extensión y tamaño de un soporte; devuelve un mensaje de error o None."""
    ext = os.path.splitext(archivo.name)[1].lower()
    if ext not in SOPORTE_EXTENSIONES:
        return f'Tipo de archivo no permitido ({ext or "sin extensión"}). Usa PDF, JPG o PNG.'
    if archivo.size > SOPORTE_MAX_BYTES:
        return 'El archivo supera el tamaño máximo de 10 MB.'
    return None
