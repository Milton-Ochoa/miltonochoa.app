# Área `logistica`

Área del edificio AAMO servida en su propio subdominio
(`logistica.miltonochoa.app`; dev: `logistica.lvh.me:8000`). Aquí vive el
**inventario** de la operación: artículos, bodegas, movimientos y préstamos.

## Estado

- Arranque del área: subdominio funcional con el mismo *chrome* que programación
  (sidebar, header, footer; ver `templates/base_chrome.html` /
  `templates/base_logistica.html`). Landing `log_home` (placeholder).
- **Inventario**: en construcción por fases. Próximas entregas: modelos y servicios
  de dominio (kardex inmutable + stock por bodega), catálogos (artículos, bodegas,
  categorías, terceros), entradas/salidas/traslados, préstamos bidireccionales con
  devolución parcial, dashboard con alertas y exports a Excel.

## Cómo está montada

- `logistica/urls.py` → `include('logistica.inventario.urls')` en la raíz `/`.
- `logistica/inventario/` (label `log_inventario`) es la sub-app del inventario.
  Sus tablas (cuando existan) usan el prefijo `log_` en `Meta.db_table`.
- Registro del área en `core/areas.py` (`AREAS['logistica']`); urlconf del
  subdominio en `core/urls_logistica.py`; la sub-app en `INSTALLED_APPS`.
- Los `messages` de Django se muestran como **toast** en esta área (mismo
  mecanismo que programación, en `templates/base_chrome.html`).

## Acceso

- Por grupo `area:logistica` (creado por `usuarios/migrations/0009_grupo_area_logistica.py`)
  o superusuario. Predicado `core.areas.es_personal_logistica`; decorador de vistas
  `logistica.inventario.permisos.solo_logistica`.
- Usuarios de etiqueta: se crean/resetean desde el **panel del apex** (sección
  "Usuarios — Logística"), con correo obligatorio y cambio de clave forzado en el
  primer ingreso (`PerfilEmpleado`).
- `usuarios/middleware.py` ramifica por `request.area`: en `logistica`, superusuario
  y miembros del grupo pasan (fija `request.es_personal_logistica`); el resto va al
  selector de área del apex.

> Crear un usuario de prueba (dev):
> ```python
> from django.contrib.auth.models import User, Group
> u = User.objects.create_user('logis', 'x', 'logis123')
> u.groups.add(Group.objects.get(name='area:logistica'))
> ```
