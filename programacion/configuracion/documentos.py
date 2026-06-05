"""Validación común de los documentos adjuntos a la ficha de un profesor.

Más permisivo que los soportes de pago/viáticos (`programacion.viaticos.soportes`):
aquí se admiten también documentos de Office, porque un CV o una hoja de vida suele
llegar en Word/Excel además de PDF o imagen. Vive aparte para no acoplar el catálogo
de profesores al flujo de pagos.
"""
import os

DOCUMENTO_EXTENSIONES = {
    '.pdf', '.jpg', '.jpeg', '.png',
    '.doc', '.docx', '.xls', '.xlsx',
}
DOCUMENTO_MAX_BYTES = 10 * 1024 * 1024  # 10 MB


def validar_documento(archivo):
    """Valida extensión y tamaño de un documento; devuelve un mensaje de error o None."""
    ext = os.path.splitext(archivo.name)[1].lower()
    if ext not in DOCUMENTO_EXTENSIONES:
        return (f'Tipo de archivo no permitido ({ext or "sin extensión"}). '
                'Usa PDF, imagen (JPG/PNG) o documento de Office (Word/Excel).')
    if archivo.size > DOCUMENTO_MAX_BYTES:
        return 'El archivo supera el tamaño máximo de 10 MB.'
    return None
