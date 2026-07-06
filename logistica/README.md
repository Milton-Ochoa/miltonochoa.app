# Área `logistica`

Área del edificio AAMO servida en su propio subdominio
(`logistica.miltonochoa.app`; dev: `logistica.lvh.me:8000`). Aquí viven el
**inventario** de la operación (artículos, bodegas, movimientos y préstamos) y la
**personalización** de PDFs (rellena plantillas AcroForm por estudiante).

## Estado

- Área **completa y funcional** (fases 1-6 cerradas): subdominio con el mismo
  *chrome* que programación (sidebar, header, footer; ver
  `templates/base_chrome.html` / `templates/base_logistica.html`).
- **Dashboard** (`log_home`): tarjetas (artículos activos, unidades totales, bajo
  mínimo, "Nos deben" / "Debemos devolver" con sus vencidos) + últimos 10
  movimientos. Badges en el menú (Existencias = items bajo mínimo, Préstamos =
  vencidos) vía el context processor `alertas_inventario`.
- **Catálogos**: artículos (`log_items_lista`), bodegas/categorías (bajo
  `/catalogos/`), terceros (con alta AJAX al vuelo) y existencias (`log_stock`).
- **Movimientos**: entradas (con adjuntos PDF/JPG/PNG ≤10 MB, descarga proxiada),
  salidas, traslados entre bodegas, kardex por artículo y ledger global
  (últimos 500; el histórico completo sale por el export). Ajuste manual con
  motivo obligatorio desde el modal de existencias.
- **Préstamos bidireccionales** (`Prestamo.direccion`): OTORGADO (prestamos
  nosotros, descuenta stock) y RECIBIDO (nos prestan, suma stock), con
  devolución parcial/total por modal en el detalle y resaltado de vencidos.
- **Exports a Excel** (openpyxl, desde modales con filtros): existencias,
  movimientos (histórico completo) y préstamos.

### Personalización de PDFs (sub-app `logistica.personalizacion`)

Módulo aparte del inventario (label `log_personalizacion`, tabla
`log_plantillas_personalizacion`). Reemplaza los 11 scripts CLI de
`Automatizacion_PDFs`: rellena campos AcroForm de plantillas PDF con **PyMuPDF**
(`import fitz`), aplana con `doc.bake()` y une **una hoja por estudiante**.

- **Plantillas** (`PlantillaPersonalizacion`): se suben, nombran, tipan y borran
  libremente (guardadas permanentemente). Dos tipos: **Simulacro** (8 campos, el
  mismo estudiante arriba/abajo, 1 por hoja, solo colegio) y **Pensar** (12 campos,
  2 estudiantes distintos por hoja, colegio + número de prueba). Aviso suave si la
  plantilla no trae todos los campos que el tipo espera.
- **Generación** (`/personalizacion/generar/`): elige plantilla + colegio (+ número
  de prueba si es Pensar) y sube un **Excel** de estudiantes (columnas `Nombres`,
  `Grado`, `Usuario`; NO se persisten). Devuelve el PDF final. Es storage-agnóstica
  (abre la plantilla desde bytes, nunca por ruta: en prod el storage es S3/Supabase).
- **Permisos**: módulo `personalizacion` del área; generar es un POST "de lectura"
  (accesible en nivel LECTURA); subir/eliminar exigen COMPLETO.

## Cómo está montada

- `logistica/urls.py` → `include('logistica.inventario.urls')` y
  `include('logistica.personalizacion.urls')` en la raíz `/`.
- `logistica/inventario/` (label `log_inventario`) es la sub-app del inventario y
  `logistica/personalizacion/` (label `log_personalizacion`) la de personalización.
  Sus tablas usan el prefijo `log_` en `Meta.db_table` (registro completo en
  la sección _Inventario de logística_ de `CLAUDE.md`).
- **Reglas de oro del dominio** (detalle en `CLAUDE.md`): `Movimiento` es un
  ledger **append-only** (kardex; los errores se corrigen con
  contramovimiento/ajuste, jamás edición/borrado) y `Stock` (denormalizado por
  item×bodega) **solo lo escriben los servicios** de
  `logistica/inventario/services.py` (transaccionales, `select_for_update`).
  Las vistas nunca tocan Stock/Movimiento directo.
- Registro del área en `core/areas.py` (`AREAS['logistica']`); urlconf del
  subdominio en `core/urls_logistica.py`; la sub-app en `INSTALLED_APPS`.
- Los `messages` de Django se muestran como **toast** en esta área (mismo
  mecanismo que programación, en `templates/base_chrome.html`).
- En `/admin/` todo está registrado; `Movimiento` y `Stock` son solo lectura.

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
