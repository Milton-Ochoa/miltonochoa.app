"""Resolución de permisos por módulo (área × usuario).

Combina el acceso **base por grupo** (`area:<area>` → todo COMPLETO; sin grupo →
SIN_ACCESO) con los **overrides sparse** de `ModuloUsuario`, que pisan módulo a módulo.
Es la única fuente de verdad del acceso granular; la lee el middleware (FASE 3) y los
predicados `es_personal_*` / `areas_del_usuario` de `core.areas`.

Los perfiles colegio/profesor NUNCA pasan por aquí: el middleware los maneja en sus
propias ramas, intactas.
"""
from core.areas import (GRUPO_STAFF_FINANCIERA, GRUPO_STAFF_LOGISTICA,
                        GRUPO_STAFF_PROGRAMACION)
from core.modulos import slugs_de_area

# Niveles (valores de ModuloUsuario.Nivel; se mantienen en sync — ver test de sanidad).
SIN = 'SIN'
LEC = 'LEC'
COM = 'COM'

_GRUPO_DE_AREA = {
    'programacion': GRUPO_STAFF_PROGRAMACION,
    'financiera': GRUPO_STAFF_FINANCIERA,
    'logistica': GRUPO_STAFF_LOGISTICA,
}


def resolver_acceso_area(user, area):
    """-> (tiene_acceso_al_area: bool, {slug_modulo: nivel}).

    - Superusuario: todos los módulos COMPLETO.
    - base = COMPLETO en todos los módulos si el usuario tiene el grupo del área; si no,
      SIN_ACCESO en todos.
    - overrides = filas `ModuloUsuario(user, area)` pisan el base módulo a módulo.
    - acceso = existe algún módulo con nivel != SIN (un solo módulo cruzado basta para
      entrar al área).
    """
    slugs = slugs_de_area(area)
    if not user.is_authenticated:
        return False, {s: SIN for s in slugs}
    if user.is_superuser:
        return True, {s: COM for s in slugs}

    grupo = _GRUPO_DE_AREA.get(area)
    # Evaluar el grupo primero permite cortocircuitar; la query de overrides solo pesa si
    # el usuario configuró alguno.
    tiene_grupo = bool(grupo and user.groups.filter(name=grupo).exists())
    modulos = {s: (COM if tiene_grupo else SIN) for s in slugs}

    from usuarios.models import ModuloUsuario  # import diferido: evita circular
    for ov in ModuloUsuario.objects.filter(user=user, area=area):
        if ov.modulo in modulos:   # ignora slugs obsoletos del catálogo
            modulos[ov.modulo] = ov.nivel

    acceso = any(n != SIN for n in modulos.values())
    return acceso, modulos


def tiene_overrides_en(user, area):
    """-> bool: el usuario tiene algún override que le da acceso (nivel != SIN) al área.

    Lo usan `es_personal_*` y `areas_del_usuario` para reconocer el acceso cruzado (un
    módulo de otra área sin pertenecer a su grupo).
    """
    if not user.is_authenticated:
        return False
    from usuarios.models import ModuloUsuario  # import diferido
    return (ModuloUsuario.objects.filter(user=user, area=area)
            .exclude(nivel=SIN).exists())
