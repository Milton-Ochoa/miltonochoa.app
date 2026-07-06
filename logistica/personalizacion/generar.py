"""Servicio de generación de PDFs personalizados.

Reduce los 11 scripts casi idénticos de `Automatizacion_PDFs` a un dict de
configuración por tipo + una función parametrizada. Es storage-agnóstico:
recibe los BYTES de la plantilla (nunca una ruta de disco), porque en prod el
storage es S3/Supabase. No toca Django ni el ORM → testeable en unidad puro.

Reglas de oro heredadas de los scripts originales:
- Reabrir la plantilla LIMPIA por cada hoja (si no, los campos homónimos quedan
  enlazados entre hojas y comparten valor).
- `doc.bake()` aplana cada hoja antes de unirla (imprescindible: sin aplanar,
  los widgets con el mismo nombre siguen ligados en el PDF final).
"""
import fitz

SECCIONES = ('Arriba', 'Abajo')


def _campos_simulacro(est, ctx, s):
    """SIMULACRO: 4 campos por sección; ambas secciones = MISMO estudiante."""
    return {
        f'Nombre{s}':  est['nombre'],
        f'Curso{s}':   est['grado'],
        f'Usuario{s}': est['usuario'],
        f'Colegio{s}': ctx['colegio'],
    }


def _campos_pensar(est, ctx, s):
    """PENSAR: 6 campos por sección; cada sección = un estudiante distinto."""
    return {
        f'Nombre{s}':       est['nombre'],
        f'Curso{s}':        est['grado'],
        f'Usuario{s}':      est['usuario'],
        f'Colegio{s}':      ctx['colegio'],
        f'PruebaDecena{s}': ctx['decena'],
        f'PruebaUnidad{s}': ctx['unidad'],
    }


# 'consumo' = estudiantes por hoja; 'asignacion' = cómo se reparten entre
# secciones ('mismo' = el mismo en Arriba y Abajo; 'por_seccion' = uno por sección).
TIPOS = {
    'SIMULACRO': {'consumo': 1, 'asignacion': 'mismo',       'campos': _campos_simulacro},
    'PENSAR':    {'consumo': 2, 'asignacion': 'por_seccion', 'campos': _campos_pensar},
}


def campos_esperados(tipo):
    """Conjunto de nombres de campo que el tipo rellena (ambas secciones).
    Se usa para el aviso suave de plantillas incompletas (`validaciones`)."""
    fn = TIPOS[tipo]['campos']
    esp = set()
    vacio_est = {'nombre': '', 'grado': '', 'usuario': ''}
    vacio_ctx = {'colegio': '', 'decena': '', 'unidad': ''}
    for s in SECCIONES:
        esp |= set(fn(vacio_est, vacio_ctx, s))
    return esp


def generar_pdf(*, plantilla_bytes, tipo, estudiantes, contexto):
    """Genera el PDF final uniendo una hoja por grupo de estudiantes.

    - `plantilla_bytes`: bytes del PDF plantilla (AcroForm).
    - `tipo`: 'SIMULACRO' | 'PENSAR'.
    - `estudiantes`: list[dict] con claves `nombre`/`grado`/`usuario`.
    - `contexto`: dict con `colegio` (y `decena`/`unidad` si PENSAR).

    Devuelve los bytes del PDF resultante.
    """
    cfg = TIPOS[tipo]
    paso = cfg['consumo']
    salida = fitz.open()
    try:
        for i in range(0, len(estudiantes), paso):
            grupo = estudiantes[i:i + paso]
            doc = fitz.open(stream=plantilla_bytes, filetype='pdf')  # plantilla LIMPIA por hoja
            try:
                pagina = doc[0]
                valores = {}
                if cfg['asignacion'] == 'mismo':
                    for s in SECCIONES:
                        valores.update(cfg['campos'](grupo[0], contexto, s))
                else:  # 'por_seccion': un estudiante por sección (la última puede faltar)
                    for idx, s in enumerate(SECCIONES):
                        if idx < len(grupo):
                            valores.update(cfg['campos'](grupo[idx], contexto, s))
                for w in pagina.widgets():
                    if w.field_name in valores:
                        # str(): blinda contra grado/usuario numéricos.
                        w.field_value = str(valores[w.field_name])
                        w.update()
                doc.bake()  # aplana: desliga los campos homónimos entre hojas
                salida.insert_pdf(doc)
            finally:
                doc.close()
        return salida.tobytes()
    finally:
        salida.close()
