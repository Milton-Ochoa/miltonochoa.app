import re
import calendar
from datetime import date, timedelta


def extraer_numero_grado(grado_str):
    """
    Extrae el primer número entero de un nombre de grado.

    Devuelve 0 como centinela cuando el grado no contiene dígitos (por ejemplo,
    'Jardín', 'Pre-K'). Esto permite usar la función como clave de ordenamiento
    sin casos especiales en el llamador.
    """
    nums = re.findall(r'\d+', str(grado_str))
    return int(nums[0]) if nums else 0


def ordenar_grados(grados):
    """
    Ordena grados con la lógica específica del sistema AAMO:

    1. Grados académicos (empiezan con dígito, ej: '11', '10-2', '9 - 1'):
       ordenados de mayor a menor por número principal, y dentro del mismo
       número, de menor a mayor por paralelo/grupo (ej: 11-1 antes que 11-2).
    2. Grupos especiales (no empiezan con dígito, ej: 'Jardín', 'Grupo 1'):
       ordenados ascendentemente por número interno, luego alfabéticamente.
       Aparecen siempre después de los grados académicos.

    Esta separación refleja cómo se visualizan en el dashboard: los grados
    superiores al tope de la tabla y los especiales al final.
    """
    def es_grado_tradicional(g):
        return bool(re.match(r'^\d', str(g).strip()))

    def clave_grado_tradicional(g):
        nums = re.findall(r'\d+', str(g))
        primer  = int(nums[0]) if nums else 0
        segundo = int(nums[1]) if len(nums) > 1 else 0
        # Negativo en primer para orden descendente; segundo ascendente para paralelos
        return (-primer, segundo)

    tradicionales = sorted(
        [g for g in grados if es_grado_tradicional(g)],
        key=clave_grado_tradicional,
    )
    especiales = sorted(
        [g for g in grados if not es_grado_tradicional(g)],
        key=lambda g: (extraer_numero_grado(g), str(g)),
    )
    return tradicionales + especiales


def calcular_rango_fechas(tipo_vista, fecha_ref):
    """
    Calcula el rango de fechas para una ventana de visualización.

    Args:
        tipo_vista: 'Semana', 'Mes' o 'Año'.
        fecha_ref:  Fecha de referencia dentro del rango deseado.

    Returns:
        Tupla (fecha_inicio: date, dias_totales: int).

    Nota: Para años bisiestos usa calendar.isleap() en lugar de year % 4 == 0,
    que es incorrecto para años de siglo (1900 no es bisiesto, 2000 sí lo es).
    """
    if tipo_vista == 'Semana':
        # weekday() devuelve 0=lunes, por lo que restar da el lunes de esa semana
        inicio = fecha_ref - timedelta(days=fecha_ref.weekday())
        dias_totales = 7
    elif tipo_vista == 'Mes':
        inicio = fecha_ref.replace(day=1)
        # Avanzar 32 días garantiza pasar al mes siguiente sin importar la longitud del mes actual
        next_month = (inicio + timedelta(days=32)).replace(day=1)
        dias_totales = (next_month - inicio).days
    else:  # Año
        inicio = date(fecha_ref.year, 1, 1)
        dias_totales = 366 if calendar.isleap(fecha_ref.year) else 365
    return inicio, dias_totales

