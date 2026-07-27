"""Catálogo de módulos por área para los permisos granulares por módulo.

Datos **puros** (sin imports de modelos ni de Django) que describen, por área, qué
prefijos de URL pertenecen a cada "módulo" gateable. La resolución de permisos
(``usuarios/permisos.py``) y el enforcement en el middleware (FASE 3) leen este
catálogo; aquí no hay comportamiento en runtime todavía.

Conceptos:
  - **NÚCLEO**: rutas accesibles a CUALQUIERA con acceso al área (grupo u override), no
    configurables por módulo. La landing del área (``/``, match exacto vía ``es_raiz``)
    siempre pasa — es bucle-safe: el redirect de "SIN ACCESO" apunta a la landing.
  - **EXENTAS**: rutas exentas del gate de módulo en TODA área (además de RUTAS_PUBLICAS
    del middleware). Se evalúan antes que el gate (p. ej. el cambio de clave forzado).
  - **Módulo**: grupo de prefijos de path dentro del subdominio que se puede poner por
    usuario en SIN_ACCESO / LECTURA / COMPLETO.
  - **posts_lectura**: paths de POST que en realidad son LECTURAS (exports a Excel) y por
    tanto se permiten aun en modo LECTURA. **Se comparan por IGUALDAD EXACTA** (no por
    prefijo): en programación los exports de pagos/monitores son POST a la RAÍZ de la
    lista del módulo (``/pagos/``, ``/monitores/pagos/``), que es prefijo de sus rutas de
    escritura (``/pagos/enviar/``, …); un match por prefijo abriría esas escrituras.
    Exacto es además estrictamente más seguro para el resto (sus exports son rutas hoja
    propias como ``/stock/exportar/``).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Modulo:
    slug: str
    nombre: str                # etiqueta para la UI del panel
    prefijos: tuple            # prefijos de path dentro del subdominio (longest-prefix gana)
    posts_lectura: tuple = ()  # POSTs "de lectura" (exports) permitidos en LECTURA (match EXACTO)


# Un módulo por grupo de rutas gateable, por área. El orden es el de presentación en el
# panel. Los prefijos se verificaron contra los urls.py reales de cada sub-app.
MODULOS = {
    'programacion': (
        Modulo('colegios', 'Colegios y cancelaciones', ('/colegios/', '/reportes/'),
               ('/reportes/cancelaciones/excel/',)),
        Modulo('profesores', 'Profesores', ('/profesores/',)),
        Modulo('informes', 'Informes', ('/informes/',)),
        Modulo('auditoria', 'Auditoría', ('/auditoria/',)),
        # El export de pagos es POST a la raíz de la lista (/pagos/) → exacto.
        Modulo('pagos', 'Pagos a profesores', ('/pagos/',), ('/pagos/',)),
        Modulo('viaticos', 'Viáticos', ('/viaticos/',)),
        # Idem monitores: export POST a /monitores/pagos/ (la lista), exacto.
        Modulo('monitores', 'Simulacros y monitores', ('/monitores/',), ('/monitores/pagos/',)),
        Modulo('exportar', 'Exportar horarios', ('/exportar/',), ('/exportar/',)),
        Modulo('configuracion', 'Configuración y usuarios', ('/configuracion/', '/usuarios/')),
    ),
    'financiera': (
        Modulo('viaticos', 'Viáticos', ('/viaticos/',), ('/viaticos/exportar/',)),
        Modulo('pagos', 'Pagos a profesores', ('/pagos/',), ('/pagos/exportar/',)),
        # proyeccion es sub-prefijo de pagos → modulo_de_path resuelve por prefijo MÁS LARGO.
        Modulo('proyeccion', 'Proyección de pagos', ('/pagos/proyeccion/',),
               ('/pagos/proyeccion/exportar/',)),
        Modulo('monitores', 'Pagos a monitores', ('/monitores/',),
               ('/monitores/pagos/exportar/',)),
    ),
    'logistica': (
        Modulo('articulos', 'Artículos y kardex', ('/articulos/',)),
        Modulo('catalogos', 'Catálogos y terceros', ('/catalogos/', '/terceros/')),
        Modulo('stock', 'Existencias', ('/stock/', '/ajustes/'), ('/stock/exportar/',)),
        Modulo('movimientos', 'Movimientos',
               ('/entradas/', '/salidas/', '/traslados/', '/movimientos/'),
               ('/movimientos/exportar/',)),
        Modulo('prestamos', 'Préstamos', ('/prestamos/',), ('/prestamos/exportar/',)),
        # generar es POST "de lectura": no escribe BD, produce un PDF (como un export)
        # → accesible en LECTURA. Es ruta hoja (no prefijo de las de escritura), match exacto.
        Modulo('personalizacion', 'Personalización', ('/personalizacion/',),
               ('/personalizacion/generar/',)),
        # Cargar/marcar/cambiar material = escrituras (COMPLETO); tablero/detalle
        # + el export son LECTURA. El export es ruta hoja (match EXACTO seguro).
        Modulo('despachos', 'Despachos', ('/despachos/',), ('/despachos/exportar/',)),
        # Registrar la devolución escribe stock (COMPLETO); lista/detalle y el
        # export son LECTURA. Ruta hoja → el match exacto del export es seguro.
        Modulo('devoluciones', 'Devoluciones de colegios', ('/devoluciones/',),
               ('/devoluciones/exportar/',)),
    ),
}

# Núcleo por área (además de la raíz '/'): rutas transversales no gateables. La landing
# ('/') la cubre `es_raiz` en el gate, no hace falta listarla aquí.
NUCLEO = {
    'programacion': ('/pendientes/', '/buscar/', '/historial/', '/general/'),
    'financiera': (),
    'logistica': (),
}

# Exenciones globales dentro de área (se evalúan antes del gate de módulo): el cambio de
# clave forzado y el auto-servicio de reseteo deben ser alcanzables sin acceso a módulos.
EXENTAS = ('/usuarios/cambiar-password/', '/usuarios/reset/')


def es_raiz(path):
    """True si `path` es la raíz del subdominio (home/landing del área)."""
    return path == '/'


def modulo_de_path(area, path):
    """Módulo cuyo prefijo MÁS LARGO casa con `path`, o None (núcleo/infra/no catalogado).

    El longest-prefix es obligatorio para desambiguar sub-prefijos (p. ej. financiera
    `/pagos/proyeccion/` gana a `/pagos/`).
    """
    mejor = None
    mejor_len = -1
    for mod in MODULOS.get(area, ()):
        for pre in mod.prefijos:
            if path.startswith(pre) and len(pre) > mejor_len:
                mejor, mejor_len = mod, len(pre)
    return mejor


def slugs_de_area(area):
    """Slugs de los módulos del área, en orden de catálogo."""
    return [m.slug for m in MODULOS.get(area, ())]


def modulo_por_slug(area, slug):
    """El `Modulo` del área con ese slug, o None."""
    for m in MODULOS.get(area, ()):
        if m.slug == slug:
            return m
    return None
