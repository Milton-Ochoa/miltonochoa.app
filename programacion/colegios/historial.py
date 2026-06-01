"""
Utilidades de auditoría para registrar y filtrar cambios en el sistema.

Estas funciones son el punto de entrada único para crear entradas de HistorialCambio.
Toda vista que cree, edite o elimine Clases, Bloques o Asignaciones debe llamar
a registrar_cambio() para mantener el historial consistente.
"""
import logging

logger = logging.getLogger('aamo')


def registrar_cambio(request, tipo, objeto, colegio=None, detalle=''):
    """
    Crea una entrada de HistorialCambio para el objeto dado.

    Args:
        request: HttpRequest actual. Puede ser None en contextos de management commands.
        tipo:    Constante de HistorialCambio (TIPO_CREAR, TIPO_EDITAR, TIPO_ELIMINAR).
        objeto:  Instancia del modelo modificado. Se llama str() para guardar snapshot.
        colegio: ColegioAnio relacionado (para filtrado por colegio en historial).
        detalle: Texto o JSON adicional con contexto del cambio (opcional).
    """
    # Import diferido para romper la dependencia circular:
    # views.py → historial.py → models.py → (ya importado) — si se importara
    # HistorialCambio en el top-level, Python fallaría al arrancar la app.
    from .models import HistorialCambio
    usuario = request.user if request and request.user.is_authenticated else None
    HistorialCambio.objects.create(
        objeto_tipo=type(objeto).__name__,
        objeto_id=objeto.pk,
        objeto_str=str(objeto)[:300],
        colegio=colegio,
        tipo=tipo,
        usuario=usuario,
        detalle=detalle,
    )


def aplicar_filtros_historial(qs, params):
    """
    Aplica filtros de búsqueda sobre un queryset de HistorialCambio.

    Usado tanto en historial_colegio (scope de un colegio) como en
    historial_global de core/ (scope de todo el sistema). Los filtros son
    opcionales y se acumulan (AND). Parámetros no presentes o vacíos se ignoran.

    Args:
        qs:     Queryset base de HistorialCambio, ya filtrado por colegio si aplica.
        params: Dict-like de parámetros GET (request.GET).

    Returns:
        Tupla (qs_filtrado, dict_filtros) donde dict_filtros contiene los valores
        actuales para repoblar el formulario en el template.
    """
    filtros = {
        'tipo_filtro':    params.get('tipo', ''),
        'objeto_filtro':  params.get('objeto', ''),
        'fecha_desde':    params.get('desde', ''),
        'fecha_hasta':    params.get('hasta', ''),
        'colegio_filtro': params.get('colegio', ''),
    }
    if filtros['tipo_filtro']:
        qs = qs.filter(tipo=filtros['tipo_filtro'])
    if filtros['objeto_filtro']:
        qs = qs.filter(objeto_tipo__icontains=filtros['objeto_filtro'])
    if filtros['fecha_desde']:
        qs = qs.filter(fecha__date__gte=filtros['fecha_desde'])
    if filtros['fecha_hasta']:
        qs = qs.filter(fecha__date__lte=filtros['fecha_hasta'])
    if filtros['colegio_filtro']:
        # Navegar por la FK doble: HistorialCambio.colegio (ColegioAnio) → colegio (Colegio)
        qs = qs.filter(colegio__colegio__nombre__icontains=filtros['colegio_filtro'])
    return qs, filtros
