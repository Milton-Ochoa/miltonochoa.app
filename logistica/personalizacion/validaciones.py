"""Validación de las plantillas PDF de personalización.

Dos niveles:
- `validar_plantilla_pdf` — validación DURA (bloquea la subida): solo `.pdf` y
  ≤10 MB. Espejo de `logistica.inventario.adjuntos.validar_adjunto` restringido
  a PDF.
- `campos_faltantes` — aviso SUAVE (no bloquea): compara los campos AcroForm
  reales de la plantilla contra los que el tipo espera rellenar, para avisar por
  `messages.warning` si la plantilla no trae todos los campos.
"""
import os

import fitz

from .generar import campos_esperados

PLANTILLA_MAX_BYTES = 10 * 1024 * 1024  # 10 MB


def validar_plantilla_pdf(archivo):
    """Valida extensión y tamaño; devuelve un mensaje de error o None."""
    ext = os.path.splitext(archivo.name)[1].lower()
    if ext != '.pdf':
        return f'Tipo de archivo no permitido ({ext or "sin extensión"}). Solo PDF.'
    if archivo.size > PLANTILLA_MAX_BYTES:
        return 'El archivo supera el tamaño máximo de 10 MB.'
    return None


def campos_del_pdf(plantilla_bytes):
    """Conjunto de nombres de campo AcroForm presentes en la primera página."""
    doc = fitz.open(stream=plantilla_bytes, filetype='pdf')
    try:
        return {w.field_name for w in doc[0].widgets() if w.field_name}
    finally:
        doc.close()


def campos_faltantes(plantilla_bytes, tipo):
    """Campos que el tipo espera rellenar pero la plantilla NO trae. Aviso
    suave: un conjunto vacío = la plantilla los tiene todos. Si el PDF está
    dañado o sin formulario, devuelve todos los esperados."""
    try:
        presentes = campos_del_pdf(plantilla_bytes)
    except Exception:
        presentes = set()
    return sorted(campos_esperados(tipo) - presentes)
