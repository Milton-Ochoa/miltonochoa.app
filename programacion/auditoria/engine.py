"""
Motor de auditoría de programación: detecta errores en el calendario de clases
y mantiene sincronizado el modelo AlertaAuditoria.

Tipos de error detectados:
  - DUPLICADO: misma unidad de la misma materia programada más de una vez en el mismo grado.
  - CONFLICTO: un profesor asignado a clases en dos colegios distintos el mismo día.
  - SECUENCIA: salto en la numeración de unidades (ej. pasó de la 2 a la 4 sin dar la 3).

Puede invocarse desde el management command `ejecutar_auditoria` o desde un hilo
en segundo plano al cargar la vista de auditoría.
"""
import hashlib
from collections import defaultdict
from datetime import date

from django.core.cache import cache
from django.utils import timezone

from auditoria.models import AlertaAuditoria
from colegios.models import Clase, Asignacion

# Clave de caché compartida entre engine.py y signals.py.
# CRÍTICO: si algún módulo invalida la caché, debe usar esta misma constante
# para que la invalidación sea efectiva. Nunca hardcodear la clave en otro lugar.
_CACHE_KEY = 'auditoria_ultima_sync'

# Tiempo de enfriamiento entre sincronizaciones automáticas (5 min).
# Evita que múltiples requests concurrentes disparen un barrido completo de BD.
_CACHE_TTL = 300

# Render (producción) no tiene locale 'es' configurado, por lo que strftime('%b')
# devuelve el nombre en inglés. Se usa este array para garantizar español en todos
# los entornos sin depender del locale del sistema operativo.
_MESES_ES = ['', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
             'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']


def _fecha_es(d):
    """Devuelve la fecha como '15 Mar' en español, independiente del locale del servidor."""
    return f"{d.day} {_MESES_ES[d.month]}"


def _huella(*partes):
    """
    Genera un hash MD5 determinista a partir de los componentes que identifican
    un error concreto. Permite deduplicar alertas sin necesidad de buscar por
    múltiples campos: si la huella ya existe en BD, el error ya está registrado.

    El separador '|' reduce (sin eliminar) las colisiones entre combinaciones
    como ('ab', 'c') y ('a', 'bc').
    """
    raw = '|'.join(str(p) for p in partes)
    return hashlib.md5(raw.encode()).hexdigest()


def _detectar_errores(anio):
    """
    Escanea todas las clases activas del año y retorna una lista de dicts con
    los errores encontrados, listos para persistir como AlertaAuditoria.

    Estrategia de rendimiento:
    - Una sola query para clases + select_related de todas las FK necesarias.
    - Pre-indexación de asignaciones por (colegio_id, grado_nombre) en un
      defaultdict antes del loop principal. Esto reduce el lookup de libro
      asignado de O(n×m) a O(k), donde k es el número de asignaciones del grado.
    - Tres mapas de acumulación (unidades, profesores, secuencia) que se
      construyen en un único recorrido sobre todas las clases.

    Clases excluidas del análisis:
    - Eventos (es_evento=True): no tienen unidad didáctica.
    - Canceladas: no cuentan como clase dictada.
    - Material especial (libro_especial != null): se registran en el mapa de
      profesores para detectar conflictos, pero se excluyen de duplicados y
      secuencia porque tienen numeración independiente del libro asignado.
    """
    todas_clases = (
        Clase.objects
        .filter(fecha__year=anio, es_evento=False, cancelada=False)
        .select_related('colegio__colegio', 'bloque__grado', 'profesor', 'materia', 'libro_especial')
        .order_by('fecha', 'bloque__hora_inicio', 'id')
    )
    todas_asignaciones = list(Asignacion.objects.select_related('colegio__colegio', 'grado', 'libro'))

    # Pre-indexar asignaciones por (colegio_id, grado_nombre) para lookup O(k) en vez de O(n×m).
    # Sin este índice, _get_libro iteraría toda la lista de asignaciones por cada clase.
    _asig_index = defaultdict(list)
    for a in todas_asignaciones:
        _asig_index[(a.colegio_id, a.grado.nombre)].append(a)

    def _get_libro(colegio_id, grado_nombre, fecha):
        """Retorna el nombre del libro vigente para el grado en la fecha dada."""
        for a in _asig_index[(colegio_id, grado_nombre)]:
            if a.fecha_inicio and a.fecha_fin and a.fecha_inicio <= fecha <= a.fecha_fin:
                return a.libro.nombre if a.libro else 'Sin libro asignado'
        return 'Sin libro asignado'

    # Acumuladores para los tres tipos de error.
    # mapa_unidades: (colegio, grado, materia, libro, unidad) → lista de clases
    # mapa_profesores: (nombre_corto, fecha, profesor_id) → set de colegios
    # mapa_secuencia: (colegio, grado, materia, libro) → lista de clases en orden cronológico
    mapa_unidades   = defaultdict(list)
    mapa_profesores = defaultdict(set)
    mapa_secuencia  = defaultdict(list)

    # Tablas de lookup inverso para recuperar los objetos ORM al construir las alertas,
    # sin necesidad de queries adicionales dentro de los loops de detección.
    colegios_por_nombre = {}
    profesores_por_nombre = {}

    for c in todas_clases:
        # Clases sin materia o sin unidad asignada no son evaluables.
        if not c.materia_id or not c.unidad:
            continue

        mat_nombre   = c.materia.nombre
        grado_nombre = c.bloque.grado.nombre
        col_nombre   = c.colegio.nombre

        # El material especial usa su propio libro (FK libro_especial), no el libro
        # asignado al grado. Se excluye de duplicados y secuencia, pero sí
        # participa en la detección de conflictos de profesor más abajo.
        es_material_especial = c.libro_especial_id is not None
        if es_material_especial:
            libro = c.libro_especial.nombre
        else:
            libro = _get_libro(c.colegio_id, grado_nombre, c.fecha)

        colegios_por_nombre[col_nombre] = c.colegio

        if c.profesor_id:
            # La clave incluye profesor_id para manejar correctamente el caso improbable
            # de dos profesores con el mismo nombre_corto.
            mapa_profesores[(c.profesor.nombre_corto, c.fecha, c.profesor_id)].add(col_nombre)
            profesores_por_nombre[c.profesor.nombre_corto] = c.profesor

        if es_material_especial:
            continue

        if str(c.unidad).isdigit():
            mapa_unidades[(col_nombre, grado_nombre, mat_nombre, libro, c.unidad)].append(c)

        # Las socializaciones ('S') no son numéricas, así que no entran en mapa_unidades
        # pero sí en mapa_secuencia — aunque en la práctica el loop de secuencia las omite
        # porque `str(cl.unidad).isdigit()` falla para 'S'.
        mapa_secuencia[(col_nombre, grado_nombre, mat_nombre, libro)].append(c)

    errores = []

    # ── Detección de duplicados ────────────────────────────────────────────────
    # Una misma unidad dictada más de una vez en el mismo (colegio, grado, materia, libro).
    for (col, gr, mat, libro, uni), clases_list in mapa_unidades.items():
        if len(clases_list) > 1:
            fechas    = [_fecha_es(cl.fecha) for cl in clases_list]
            libro_txt = f' ({libro})' if libro else ''
            errores.append({
                'tipo': AlertaAuditoria.Tipo.DUPLICADO,
                'huella': _huella('dup', col, gr, mat, libro, uni),
                'mensaje': (
                    f"El grado {gr} tiene programada la unidad {uni} de {mat}{libro_txt} "
                    f"{len(clases_list)} veces (Fechas: {', '.join(fechas)})."
                ),
                'colegio': colegios_por_nombre.get(col),
                'profesor': None,
                'colegios_implicados': [],
            })

    # ── Detección de conflictos de profesor ───────────────────────────────────
    # Un profesor con clases en más de un colegio el mismo día es físicamente imposible.
    # La huella incluye la lista de colegios ordenada para que sea estable entre runs.
    for (profe_nombre, fecha, profe_id), colegios_set in mapa_profesores.items():
        if len(colegios_set) > 1:
            lista = sorted(colegios_set)
            errores.append({
                'tipo': AlertaAuditoria.Tipo.CONFLICTO,
                'huella': _huella('conf', profe_nombre, fecha.isoformat(), '|'.join(lista)),
                'mensaje': (
                    f"El profesor {profe_nombre} tiene clases en {len(lista)} colegios "
                    f"distintos el {_fecha_es(fecha)} ({' y '.join(lista)})."
                ),
                'colegio': None,
                'profesor': profesores_por_nombre.get(profe_nombre),
                'colegios_implicados': [
                    colegios_por_nombre[n] for n in lista if n in colegios_por_nombre
                ],
            })

    # ── Detección de saltos de secuencia ──────────────────────────────────────
    # Recorre las clases de cada (colegio, grado, materia, libro) en orden cronológico
    # (garantizado por el ORDER BY de la query principal) y emite un error cuando
    # el número de unidad salta hacia adelante >1 o retrocede.
    # Nota: una repetición (unidad_actual == ultima_unidad) no se reporta aquí;
    # ya la cubre la detección de duplicados.
    for (col, gr, mat, libro), clases_list in mapa_secuencia.items():
        ultima_unidad = None
        for cl in clases_list:
            if str(cl.unidad).isdigit():
                unidad_actual = int(cl.unidad)
                if ultima_unidad is not None and (
                    unidad_actual > ultima_unidad + 1 or unidad_actual < ultima_unidad
                ):
                    libro_txt = f' ({libro})' if libro else ''
                    errores.append({
                        'tipo': AlertaAuditoria.Tipo.SECUENCIA,
                        # La fecha forma parte de la huella para distinguir saltos distintos
                        # dentro del mismo (colegio, grado, materia) a lo largo del año.
                        'huella': _huella('sec', col, gr, mat, libro, ultima_unidad, unidad_actual, cl.fecha.isoformat()),
                        'mensaje': (
                            f"Salto de secuencia en el grado {gr} para {mat}{libro_txt}. "
                            f"Pasó de la unidad {ultima_unidad} a la {unidad_actual} "
                            f"el {_fecha_es(cl.fecha)}."
                        ),
                        'colegio': colegios_por_nombre.get(col),
                        'profesor': None,
                        'colegios_implicados': [],
                    })
                ultima_unidad = unidad_actual

    return errores


def sincronizar(forzar=False):
    """
    Sincroniza las AlertaAuditoria de BD con los errores reales detectados en clases.

    Por defecto se ejecuta como máximo una vez cada 5 minutos (controlado por caché).
    Esto evita barrer toda la BD en cada request cuando varios usuarios usan la vista
    de auditoría simultáneamente. Pasar `forzar=True` salta el throttle; úselo solo
    desde el management command o en tests.

    Lógica de reconciliación:
    1. Detectar errores actuales → obtener sus huellas.
    2. Marcar como resueltas (vigente=False) todas las alertas vigentes cuya huella
       ya no aparece en los errores actuales.
    3. Para cada error actual:
       a. Si la huella existe y la alerta estaba inactiva → reactivarla.
       b. Si la huella no existe → crear nueva alerta con get_or_create.
          (get_or_create evita IntegrityError si dos hilos sincronizan en paralelo.)

    Retorna: tupla (creadas, reactivadas, resueltas) con los conteos de cada operación.
    """
    if not forzar and cache.get(_CACHE_KEY):
        return (0, 0, 0)

    anio = date.today().year
    errores = _detectar_errores(anio)
    huellas_actuales = {e['huella'] for e in errores}
    ahora = timezone.now()

    # Paso 1: resolver en bloque todas las alertas que ya no corresponden a errores reales.
    # Se usa update() para evitar N queries individuales.
    resueltas = AlertaAuditoria.objects.filter(
        vigente=True,
    ).exclude(huella__in=huellas_actuales).update(
        vigente=False, resuelto_en=ahora,
    )

    # Paso 2: obtener en una sola query las huellas que ya existen en BD
    # (tanto vigentes como resueltas) para decidir si crear o reactivar.
    huellas_existentes = set(
        AlertaAuditoria.objects.filter(
            huella__in=huellas_actuales,
        ).values_list('huella', flat=True)
    )

    creadas = 0
    reactivadas = 0
    for err in errores:
        if err['huella'] in huellas_existentes:
            # La alerta ya existe. Reactivar solo si estaba auto-resuelta.
            # Si fue ignorada manualmente (ignorado_por != null), no se toca:
            # el admin decidió aceptar ese error conscientemente.
            alerta = AlertaAuditoria.objects.filter(
                huella=err['huella'], vigente=False, ignorado_por__isnull=True,
            ).first()
            if alerta:
                alerta.vigente = True
                alerta.resuelto_en = None
                alerta.mensaje = err['mensaje']  # el mensaje puede cambiar si cambiaron las fechas
                alerta.save(update_fields=['vigente', 'resuelto_en', 'mensaje'])
                reactivadas += 1
            continue

        # Alerta nueva. get_or_create protege contra condición de carrera si dos
        # hilos llegan aquí simultáneamente con la misma huella.
        alerta, created = AlertaAuditoria.objects.get_or_create(
            huella=err['huella'],
            defaults={
                'tipo':    err['tipo'],
                'mensaje': err['mensaje'],
                'colegio': err['colegio'],
                'profesor': err['profesor'],
            },
        )
        if created:
            if err['colegios_implicados']:
                alerta.colegios_implicados.set(err['colegios_implicados'])
            creadas += 1

    # Estampar la caché DESPUÉS de completar la escritura para que el próximo
    # hilo que entre encuentre datos frescos, no un estado intermedio.
    cache.set(_CACHE_KEY, True, _CACHE_TTL)
    return (creadas, reactivadas, resueltas)
