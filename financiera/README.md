# Área `financiera`

Área del edificio AAMO servida en su propio subdominio
(`financiera.miltonochoa.app`; dev: `financiera.lvh.me:8000`).

## Estado

- **Fase 3 (hecha):** arranque del área. Subdominio funcional con el mismo *chrome*
  que programación (sidebar, header, footer; ver `templates/base_chrome.html` /
  `templates/base_financiera.html`). Dos entradas de menú: **Inicio** (`fin_home`) y
  **Viáticos** (`fin_viaticos_lista`, placeholder).
- **Fase 4 (pendiente):** gestión real de viáticos (listar/devolver/editar/aprobar/
  pagar + badge de pendientes).

## Cómo está montada

- `financiera/urls.py` → `include('financiera.viaticos.urls')` en la raíz `/`.
- `financiera/viaticos/` es una sub-app (label `fin_viaticos`) **sin modelos
  propios**: importa `SolicitudViatico`/`GastoViatico` de `programacion.viaticos`
  (BD única, mismo patrón que `usuarios` → `programacion.configuracion`).
- Registro del área en `core/areas.py` (`AREAS['financiera']`); urlconf del
  subdominio en `core/urls_financiera.py`; el área está en `INSTALLED_APPS`.

## Acceso

- Por grupo `area:financiera` (creado por `usuarios/migrations/0006_grupo_area_financiera.py`)
  o superusuario. Predicado `core.areas.es_personal_financiera`.
- Asignación de usuarios al grupo: por ahora vía `/admin/` de Django.
- `usuarios/middleware.py` ramifica por `request.area`: en `financiera`, superusuario
  y miembros del grupo pasan; el resto va al selector de área del apex.

> Crear un usuario de prueba (dev):
> ```python
> from django.contrib.auth.models import User, Group
> u = User.objects.create_user('finan', 'x', 'finan123')
> u.groups.add(Group.objects.get(name='area:financiera'))
> ```
