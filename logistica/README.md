# Área `logistica`

Área del edificio AAMO servida en su propio subdominio
(`logistica.miltonochoa.app`; dev: `logistica.lvh.me:8000`). Aquí viven el
**inventario** de la operación (artículos, bodegas, movimientos y préstamos), la
**personalización** de PDFs (rellena plantillas AcroForm por estudiante), los
**despachos** de material (tablero de órdenes del ERP externo) y las
**devoluciones de colegios** (material que vuelve sin usar y suma al inventario).

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

### Despachos de material (sub-app `logistica.despachos`)

Módulo aparte (label `log_despachos`, tablas `log_despachos_*`). El personal despacha
material físico a colegios; las órdenes viven en un **ERP externo** del que se descarga a
diario un reporte (`.xls` que en realidad es una tabla HTML de ~26 MB). AAMO importa ese
reporte y da el tablero de órdenes por despachar.

- **Carga diaria idempotente** (`/despachos/cargar/`): sube el `.xls`; `importar_reporte`
  (única puerta de escritura, `transaction.atomic()` con upsert bulk) refresca los datos ERP
  conservando las marcas locales, sincroniza líneas, cierra órdenes anuladas y actualiza
  alertas. **Anti-archivo-viejo**: rechaza un reporte más viejo que la última carga.
- **Tablero** (`/despachos/`): 3 tabs (por despachar / despachadas sin remisión / cerradas),
  filtros por columna + atajos de fecha (vencidas / próx. 7 días / hoy / semana / mes)
  client-side, resaltado de vencidas (rojo) y próximas (amarillo), `?q=PPAL-N` salto al
  detalle. **Detalle** (`/despachos/orden/<pk>/`): datos ERP, líneas de material (FORMACIÓN
  colapsada aparte) e historial de eventos append-only.
- **Estados de trabajo** `PENDIENTE → ALISTADA → DESPACHADA` (marcar/revertir un paso) +
  terminales automáticos `REMITIDA`/`ANULADA` del import. **Verificación cruzada**: despachada
  aquí pero sin remisión en el ERP → alerta; cerrada en el ERP sin marcar → aviso.
- **Cambio de material** por línea (artículo de reemplazo + cantidad) con flag "pendiente de
  actualizar en ERP".
- **Badge** rojo de órdenes vencidas (context processor `alertas_despachos`). **Export a
  Excel** del tablero con los filtros vigentes (reutiliza el helper de inventario; permitido en
  LECTURA). **Bodega por defecto** por usuario (`AsignacionBodega`) que pre-filtra el tablero;
  la gestiona el **superusuario** en `/despachos/bodegas/`.
- **Permisos**: módulo `despachos` del área; ver tablero/detalle y exportar = LECTURA; cargar,
  marcar y cambiar material = COMPLETO.

### Devoluciones de colegios (sub-app `logistica.devoluciones`)

Sub-app de **UI sin modelos** (label `log_devoluciones`): el material que un colegio
devuelve sin usar. El dominio (`DevolucionColegio` + `DevolucionColegioLinea`, tablas
`log_devoluciones_colegios*`, y el servicio `registrar_devolucion_colegio`) vive en
`logistica.inventario`, porque toda escritura al stock/ledger pasa por sus servicios.

- **Registro** (`/devoluciones/nueva/`): cabecera comercial (fecha de recibido, colegio,
  código, regional, ejecutivo, bodega de ingreso, observaciones) + líneas con el parcial
  compartido `inventario/_lineas_material.html` (un material con sus **12 cantidades por
  grado**; la bodega es de la cabecera, no por línea). El colegio es texto libre con
  autocompletado desde los clientes del **ERP de despachos**.
- Lo devuelto **suma automáticamente** a la bodega elegida y queda en el kardex como
  movimiento `DEV_COLEGIO` (positivo), con el documento como origen (`PROTECT`).
- **Lista** con filtros por columna + paginación y **export a Excel** con el layout de la
  hoja del usuario (una fila por devolución y material; sin "Registro Effi", omitido a
  propósito). El builder del Excel (`devoluciones/export.py`) lo reutiliza financiera.
- **Permisos**: módulo `devoluciones` del área; lista/detalle y export = LECTURA;
  registrar = COMPLETO. **Sin valores monetarios** (financiera ajusta cobros aparte).

## Cómo está montada

- `logistica/urls.py` → `include('logistica.inventario.urls')`,
  `include('logistica.personalizacion.urls')`, `include('logistica.despachos.urls')` e
  `include('logistica.devoluciones.urls')` en la raíz `/`.
- `logistica/inventario/` (label `log_inventario`), `logistica/personalizacion/` (label
  `log_personalizacion`), `logistica/despachos/` (label `log_despachos`) y
  `logistica/devoluciones/` (label `log_devoluciones`, sin modelos) son las 4 sub-apps.
  Sus tablas usan el prefijo `log_` en `Meta.db_table` (registro completo en las secciones
  _Inventario de logística_ y _Despachos de material_ de `CLAUDE.md`).
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
- En `/admin/` todo está registrado; `Movimiento` y `Stock` (inventario) y
  `CargaReporte` y `EventoOrden` (despachos) son solo lectura.

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
