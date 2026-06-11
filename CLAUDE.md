# CLAUDE.md — Guía para sesiones de Claude Code

Guía interna del proyecto **AAMO**. Léela antes de tocar la estructura. Para la
documentación de usuario/instalación ver [README.md](README.md).

## Mapa del proyecto: skill `graphify` (LÉELO ANTES DE EXPLORAR)

Este repo tiene un **grafo de conocimiento** precomputado de todo el código y las
plantillas, generado por la skill **graphify** (`/graphify`). Es un mapa de "qué se
conecta con qué": modelos, vistas, plantillas, sub-apps y áreas, con sus relaciones
(`calls`, `extends`, `references`, `shares_data_with`, …), detección de comunidades y
"god nodes" (las abstracciones más conectadas).

**Por qué existe:** AAMO es un único Django grande, multi-área, con una convención no
obvia (ruta de import ≠ `app_label`, áreas servidas por subdominio, código compartido
entre `financiera`→`programacion`). Buscar a ciegas con grep es lento y se pierde el
contexto de "esto vive aquí pero pertenece a aquella área". El grafo da ese contexto de
golpe.

**Cuándo usarlo (preferentemente ANTES de un grep/glob a ciegas):**
- Para **entender el proyecto** o una zona nueva al empezar una sesión.
- Para **localizar** dónde vive una funcionalidad o quién la usa: "¿qué toca los pagos?",
  "¿qué plantillas extienden `base_chrome`?", "¿quién llama a `_responder_soporte`?".
- Para **medir el impacto** de un cambio: qué nodos dependen del modelo/vista que vas a
  tocar (mira los "god nodes" y las aristas entrantes).
- Para ver **acoplamientos cruzados** entre áreas/sub-apps que el código no grita
  (p. ej. `financiera.*` reutilizando `programacion.*`).

**Cómo consultarlo (en orden de preferencia):**
1. **Lee el resumen ya generado:** [graphify-out/GRAPH_REPORT.md](graphify-out/GRAPH_REPORT.md)
   — god nodes, conexiones sorpresa y preguntas que el grafo responde. Empieza aquí.
2. **Pregunta al grafo:** `graphify query "<pregunta>"` (BFS, contexto amplio) o
   `graphify query "<pregunta>" --dfs` (traza un camino). `graphify path "A" "B"` =
   camino más corto entre dos conceptos; `graphify explain "<nodo>"` = explicación.
3. **Visor interactivo:** abre [graphify-out/graph.html](graphify-out/graph.html) en el navegador.
4. El grafo crudo está en `graphify-out/graph.json` (NetworkX-friendly).

**Importante / mantenimiento:**
- `graphify-out/` está **gitignored** (artefacto regenerable, NO se versiona). Si no
  existe en tu copia local, regenéralo con `/graphify .` antes de apoyarte en él.
- Tras cambios de código, **actualízalo** con `/graphify . --update` (re-extrae solo lo
  modificado) para que no quede desfasado. Es un **apoyo de orientación**, no la verdad
  absoluta: las aristas `INFERRED`/`AMBIGUOUS` pueden estar equivocadas — **verifica en el
  código** antes de actuar sobre algo crítico.
- La skill se instala una vez por máquina: `uv tool install graphifyy` + `graphify install`
  (registra `~/.claude/skills/graphify/SKILL.md`). La extracción de código es AST local
  (gratis); la semántica de docs/plantillas usa la sesión como LLM (subagentes).

## README.md: skill `/readme` (ÚSALO SIEMPRE PARA ACTUALIZAR EL README)

El proyecto tiene un **skill dedicado para generar y mantener el README.md** instalado en
`~/.claude/skills/readme/SKILL.md`. Debe usarse **siempre** que haya que crear o actualizar
el README:

- **`/readme`** — reescribe el README completo desde cero.
- **`/readme --update`** — actualiza solo las secciones afectadas por cambios recientes.

**Cuándo usarlo (obligatorio):**
- Tras eliminar o añadir un área, sub-app o feature significativa.
- Tras cambios en el stack (nuevas dependencias, paquetes eliminados).
- Cuando el conteo de tests cambie notablemente (nuevo baseline).
- Cuando cambien las variables de entorno o las instrucciones de deploy.
- Cuando se refactorizó la estructura de directorios.

**Por qué:** El README es documentación pública de usuario/colaborador. Sin este skill es
fácil que quede con referencias a features eliminadas (como la API REST que se quitó),
versiones incorrectas o instrucciones que ya no funcionan. El skill lee `graphify-out/`,
`CLAUDE.md` y `requirements.txt` para producir un README fiel al estado real del código.

**Cómo mantener este CLAUDE.md actualizado:**
- Actualiza este archivo manualmente después de cada cambio estructural importante
  (nuevas áreas, modelos eliminados, convenciones nuevas, decisiones de arquitectura).
- El skill `/readme` avisa si detecta que CLAUDE.md tiene información desactualizada,
  pero **no lo edita automáticamente** — la edición es siempre manual y deliberada.

## Qué es AAMO

Un **único proyecto Django** organizado por **áreas**, cada una servida en su
**propio subdominio**. Una sola BD, un solo login. El login (en el apex) decide,
según permisos, a qué subdominio/área redirige al usuario.

- **Dominio:** `miltonochoa.app`. Apex = login único + selector de área.
- **Áreas activas hoy:** `programacion/` → `programacion.miltonochoa.app`,
  `financiera/` → `financiera.miltonochoa.app` y `logistica/` →
  `logistica.miltonochoa.app` (todas en la raíz `/` de su subdominio,
  **ya no** `/programacion/`). OJO: el subdominio `logistica` debe existir en el
  DNS de Cloudflare antes del primer deploy del área a prod.
- Dev: `BASE_DOMAIN=lvh.me` → `lvh.me:8000` (apex), `programacion.lvh.me:8000`,
  `financiera.lvh.me:8000` y `logistica.lvh.me:8000` (áreas).
- Deploy: push a `main` → Railway (auto). BD en Supabase (PostgreSQL).

## Rendimiento y concurrencia en producción (IMPORTANTE)

Una auditoría de carga reveló lentitud y **502** al usar la app de forma concurrente.
La causa NO era la lógica sino la **topología de despliegue**. Config actual (no cambiar
sin medir):

- **Gunicorn** (`railway.json` `startCommand`): `--workers 6 --threads 4 -k gthread`
  (= 24 slots concurrentes; 6 procesos = paralelismo CPU real bajo el GIL, que es lo que
  rompe la serialización bajo ráfaga), `--worker-tmp-dir /dev/shm` (heartbeat en tmpfs:
  evita kills/502 espurios en contenedores), `--max-requests 800 --max-requests-jitter 200`
  (recicla workers, evita fugas), `--timeout 90 --keep-alive 5`. **Regla:** mantener
  `workers×threads ≤ pool_size del pooler`.
- **Pooler de Supabase (transaction) OBLIGATORIO** con tantos workers. `DATABASE_URL` debe
  apuntar al **transaction pooler de Supavisor**: host `aws-<n>-<region>.pooler.supabase.com`,
  **puerto 6543**, usuario `postgres.<project_ref>` (NO `db.<ref>.supabase.co`, que Supabase
  enruta a *session mode* y agota el pool → la app **crashea** al arrancar con
  `EMAXCONNSESSION`). Con transaction pooler: `CONN_MAX_AGE=600` (conexiones calientes, baja
  TTFB) y `DISABLE_SERVER_SIDE_CURSORS=True` (psycopg2 no usa prepared statements
  server-side → compatible). Ambas leídas por env en `core/settings.py`. **`pool_size` del
  pooler = 30** (Supabase → Database → Connection Pooling; gratis, ≥ workers×threads).
- **Co-localización de región (clave para el TTFB):** Railway y Supabase deben estar en la
  **misma región**. Supabase está en `us-west-2` → el servicio Railway se movió a **US West**
  (`railway service scale us-west=1 us-east=0`). Cross-región añadía ~70 ms por query; en
  misma región ~10 ms. Si se mueve la BD, mover también el servicio.
- **Costo por request bajo:** el dashboard ya **no** dispara `sincronizar()` de auditoría
  (era un barrido global por carga); la reconciliación vive en la vista de auditoría y el
  comando `ejecutar_auditoria`. La matriz/stats del dashboard se cachean con **single-flight**
  (`_get_or_build_cached`, lock `cache.add`) para evitar herd de construcción bajo ráfaga, y
  se **invalidan al guardar Y al eliminar** clase (TTL 300 s).
- **Medición:** los problemas de concurrencia NO se reproducen con `runserver`. El arnés de
  carga (Playwright + urllib) vive fuera del repo; medir contra producción ya desplegada.

## Estructura

```
AAMO/
├── core/              # Motor: settings, middleware (enrutado por subdominio),
│   │                  #   areas.py (registro + URLs entre hosts), urls.py (apex),
│   │                  #   urls_programacion.py + urls_financiera.py + urls_logistica.py (áreas),
│   │                  #   PWA, errores
├── usuarios/          # GLOBAL: login único, perfiles, middleware de acceso, ratelimit
├── programacion/      # ÁREA: paquete Python con urls.py + sus sub-apps
│   ├── urls.py        #   agrupa las rutas del área en la RAÍZ de su subdominio
│   ├── configuracion/ colegios/ profesores/ informes/ auditoria/ exportar/ pagos/ pendientes/ viaticos/
├── financiera/        # ÁREA: urls.py + viaticos/ (Inicio + gestión; SIN modelos propios,
│   │                  #   importa los de programacion.viaticos)
├── logistica/         # ÁREA: urls.py + inventario/ (label log_inventario; modelos y
│   │                  #   servicios de dominio listos — tablas log_*; UI de catálogos,
│   │                  #   existencias, movimientos y préstamos activa; dashboard y
│   │                  #   exports en construcción)
├── templates/         # globales: base_chrome (chrome compartido), base (menú programación),
│   │                  #   base_financiera (menú financiera), base_logistica (menú logística),
│   │                  #   base_apex (lobby), home, 404/500, login, sw.js
└── backups/           # AAMO_export.xlsx (respaldo de BD)
```

**Chrome compartido:** `templates/base_chrome.html` contiene TODO el armazón visual
(CSS, sidebar, header, footer, JS de colapsar/atajos). `base.html` (programación) y
`base_financiera.html` (financiera) lo extienden y solo aportan bloques: `doc_title`,
`brand_title`, `sidebar_menu`, `header_title`, `header_center`, `content`, `extra_head`.
Las piezas de programación (búsqueda global, modales, atajos) viven en `base_chrome` pero
están gated por `request.es_personal_programacion` → inertes en otras áreas.

**Portal del profesor (perfiles `UsuarioProfesor`):** el sidebar **sí** se muestra a los
perfiles de profesor (antes `base_chrome` lo ocultaba con `{% if not
request.user.perfil_profesor %}`; ese gate, el logo-en-vez-de-hamburguesa y el footer
propio se eliminaron — el chrome es uniforme para todos los roles). Su menú (rama
`perfil_profesor` del `{% else %}` en `base.html`) tiene 3 ítems: **Cronograma**
(`ver_horario`, la vista fuerza su propio horario), **Informes** (`lista_informes`, la
vista ya scopea por rol) y **Pagos** (`profesor_pagos` → `/profesores/pagos/`, vista
`mis_pagos` en `programacion.profesores.views`; bajo `/profesores/` a propósito para no
tocar `_PERMITIDAS_PROFESOR`). **Mis pagos** muestra el estado de sus pagos por día de
clases — agrupa sus clases dictadas (`fecha__lte=hoy`, no canceladas/no eventos) por
`(fecha, bloque__colegio_id)`, el mismo grouping de `_build_filas_pagos`, y cruza con
`PagoRealizado`: *Pagada* = fila con `fecha_pago` (muestra fecha de pago + soportes);
*Pendiente* = todo lo demás (incluye días sin fila materializada y filas `excluida` —
la exclusión es interna de programación). **CONTRATO: el profesor NUNCA ve montos en
pesos** — al template (`profesores/mis_pagos.html`, dos pestañas) van dicts saneados
(fecha/colegio/horas/estado/soportes), jamás objetos `PagoRealizado`. Staff/superusuario
en esa URL → redirect a `pagos_lista`. La descarga del soporte la proxia
`profesor_soporte_descargar` (`/profesores/pagos/soporte/<id>/`), gateada al **dueño**:
404 (no 403, para no revelar existencia) si el soporte no es de su `profesor_id` o si
no hay perfil de profesor. El modal de informe de sesión está extraído a parciales
compartidos `informes/_modal_informe.html` + `_modal_informe_js.html` (los ids `inf_*` y
`modalInforme` son contrato entre ambos): los incluyen `profesores/horario.html` (usa
`profesor_sel` como profesor por defecto) e `informes/lista.html` (cada fila pasa su
`profesor_id` como 10.º argumento opcional de `abrirInforme`, y el include lleva
`recargar_al_guardar=True` → la página se recarga tras guardar). Para perfiles de
profesor el server ignora el `profesor_id` del body (blindaje en `guardar_informe`).
La lista permite **diligenciar desde la fila** (botón "Informe", oculto a gestores de
colegio): las filas de `lista_informes` traen `clase_id`/`personalizada_id`/`profesor_id`/
`tematica`; la clave de caché es `informes_lista:v2:g{gen}:user:{id}` y la invalidación
rota el contador `informes_lista:gen` (funciona igual en locmem y Redis — ya no usa
`delete_pattern`, que en locmem era un no-op).

## Convención CRÍTICA: ruta de import ≠ app_label

Las apps viven dentro de `programacion/` pero **conservan su label original**:

- En cada `apps.py`: `name = 'programacion.colegios'` **y** `label = 'colegios'`.
- Las tablas, migraciones y FK por string (`'configuracion.Colegio'`) usan el
  **label**, así que NO cambiaron al unificar.

Reglas al editar:
- **Imports Python:** siempre `from programacion.<app>.models import ...` (ruta completa).
- **FK por string / `apps.get_model('configuracion', 'Colegio')`:** usan label → **no** llevan el prefijo `programacion.`.
- **`{% url 'nombre' %}`:** los nombres de URL son globales → no cambian. Resuelven
  **dentro del host actual**; para enlazar/redirigir a OTRO subdominio usa los
  helpers de `core/areas.py` (`url_en_area`, `url_apex`), no `reverse` a secas.
- **`include()`:** `include('programacion.<app>.urls')`.
- Si tocas modelos y `makemigrations` propone algo inesperado, probablemente una
  label cambió sin querer → investiga antes de seguir.

## Nombres de tabla (`db_table`)

Las tablas **no** usan el nombre por defecto de Django (`<app_label>_<modelo>`);
cada modelo declara explícitamente su `Meta.db_table` con un nombre de dominio
limpio, en **plural snake_case**. Convención obligatoria al crear un modelo nuevo:

- **Modelos del área `programacion`:** prefijo `prog_` → `prog_<plural>`
  (ej. `prog_colegios`, `prog_clases_personalizadas`, `prog_historial_cambios`).
  El prefijo agrupa las tablas del área en el navegador de BD.
- **Modelos del área `logistica`:** prefijo `log_` → `log_<plural>` (ver la tabla en
  la sección _Inventario de logística_).
- **Modelos globales (`usuarios/`):** prefijo de dominio propio (`usuarios_…`),
  sin `prog_`, porque no pertenecen al área (login único / SSO).
- Las tablas internas de Django (`auth_*`, `django_*`) no se tocan.

Registro actual (modelo → tabla):

| Modelo | Tabla | | Modelo | Tabla |
|---|---|---|---|---|
| `Materia` | `prog_materias` | | `ClasePersonalizada` | `prog_clases_personalizadas` |
| `NombreLibro` | `prog_libros` | | `HistorialCambio` | `prog_historial_cambios` |
| `Unidad` | `prog_unidades` | | `Informe` | `prog_informes` |
| `Colegio` | `prog_colegios` | | `AlertaAuditoria` | `prog_alertas_auditoria` |
| `ColegioAnio` | `prog_colegio_anios` | | `PagoRealizado` | `prog_pagos` |
| `Profesor` | `prog_profesores` | | `Tarea` | `prog_tareas` |
| `DocumentoProfesor` | `prog_profesores_documentos` | | `UsuarioColegio` | `usuarios_colegio` |
| `Grado` | `prog_grados` | | `UsuarioProfesor` | `usuarios_profesor` |
| `Bloque` | `prog_bloques` | | `CancelacionClase` | `prog_clases_cancelaciones` |
| | | | `PerfilEmpleado` | `usuarios_empleados` |
| | | | `ErrorCliente` | `usuarios_errores_cliente` |
| `Asignacion` | `prog_asignaciones` | | `SolicitudViatico` | `prog_viaticos` |
| `Clase` | `prog_clases` | | `GastoViatico` | `prog_viaticos_gastos` |
| | | | `SoportePago` | `prog_viaticos_soportes` |
| | | | `SoportePagoProfesor` | `prog_pagos_soportes` |
| | | | `LotePagos` | `prog_pagos_lotes` |
| | | | `ExtraPago` | `prog_pagos_extras` |

- **M2M:** la tabla intermedia auto-creada se renombra **sola** al cambiar el
  `db_table` del modelo (`AlterModelTable` la arrastra) → `prog_profesores_materias`,
  `prog_alertas_auditoria_colegios_implicados`. No requiere operación manual.
- Cambiar un `db_table` genera un `AlterModelTable` que ejecuta `ALTER TABLE …
  RENAME` (renombra, **no** borra: conserva los datos en SQLite y PostgreSQL).

## Inventario de logística (sub-app `logistica.inventario`, label `log_inventario`)

Sistema de inventario por cantidades (sin seriales ni costos: el kardex es de
**cantidades**, `Item.valor_unitario` es solo referencial para exports). Multi-bodega,
préstamos **bidireccionales** (`Prestamo.direccion`: OTORGADO = prestamos nosotros,
RECIBIDO = nos prestan) con devolución parcial, y ajustes con motivo obligatorio.
Modelos en `logistica/inventario/models.py` (migración `log_inventario.0001_initial`):

| Modelo | Tabla | | Modelo | Tabla |
|---|---|---|---|---|
| `Categoria` | `log_categorias` | | `Salida` | `log_salidas` |
| `Bodega` | `log_bodegas` | | `SalidaLinea` | `log_salidas_lineas` |
| `Item` | `log_articulos` | | `Traslado` | `log_traslados` |
| `Tercero` | `log_terceros` | | `TrasladoLinea` | `log_traslados_lineas` |
| `Stock` | `log_stock` | | `Prestamo` | `log_prestamos` |
| `Movimiento` | `log_movimientos` | | `PrestamoLinea` | `log_prestamos_lineas` |
| `Entrada` | `log_entradas` | | `Devolucion` | `log_prestamos_devoluciones` |
| `EntradaLinea` | `log_entradas_lineas` | | | |
| `AdjuntoEntrada` | `log_entradas_adjuntos` | | | |

Reglas de oro (NO romper):

- **`Movimiento` es un ledger append-only** (kardex): jamás vistas de edición/borrado;
  los errores se corrigen con contramovimiento/ajuste. Cada fila guarda
  `saldo_resultante` (saldo de item×bodega tras aplicar, calculado bajo lock) → kardex
  con saldo sin window functions. `cantidad` siempre > 0; el signo lo da el `tipo`
  (property `delta`). FK `PROTECT` a su documento de origen.
- **`Stock` (denormalizado por item×bodega) SOLO lo escriben los servicios** de
  `logistica/inventario/services.py` — única puerta de escritura, las vistas nunca lo
  tocan directo. Todo es `transaction.atomic` con `select_for_update` (no-op en
  SQLite/dev/tests; la exclusión real solo existe en PostgreSQL — la última barrera es
  el CHECK ≥ 0 de `PositiveIntegerField`). Si una línea falla, NADA queda escrito.
- **Servicios:** `registrar_entrada(bodega, lineas=[(Item, cant)], usuario, proveedor='',
  observaciones='')`, `registrar_salida(bodega, lineas, usuario, tercero=None,
  tercero_nombre='', motivo='', observaciones='')`, `registrar_traslado(bodega_origen,
  bodega_destino, lineas, usuario, observaciones='')` (TRASLADO_SAL + TRASLADO_ENT
  atómicos), `crear_prestamo(tercero, fecha_compromiso, lineas=[(Item, Bodega, cant)],
  usuario, direccion=OTORGADO, observaciones='')`, `registrar_devolucion(prestamo,
  lineas=[(PrestamoLinea, cant)], usuario, observaciones='')` (opera sobre la bodega de
  cada línea; recalcula estado PARCIAL/CERRADO), `registrar_ajuste(item, bodega,
  nueva_cantidad, usuario, motivo)` (motivo obligatorio). Todos keyword-only. Excepciones
  de dominio: `StockInsuficiente` (item/bodega/disponible/solicitado) y `ErrorDevolucion`
  → las vistas las traducen a `messages.error`. Consultas: `kardex(item, bodega=None,
  desde=None, hasta=None)`, `items_bajo_minimo()` (mínimo **global** por item, suma de
  bodegas; 0 = sin alerta), `prestamos_vencidos()` (ambas direcciones).
- **Snapshots de texto** (patrón `CancelacionClase`): `Salida.tercero_nombre`,
  `Prestamo.tercero_nombre/_documento` — los documentos sobreviven al borrado del
  `Tercero` (FK `SET_NULL`).
- **UI de documentos (F4):** las vistas de entradas/salidas/traslados validan la cabecera
  con un form (`EntradaForm`/`SalidaForm`/`TrasladoForm` en `forms.py`) y las líneas con
  `forms.parsear_lineas` (lee las listas paralelas `linea_item`/`linea_cantidad` —y
  `linea_bodega` con `con_bodega=True`, para préstamos— del parcial compartido
  `inventario/_lineas_doc.html`); el documento lo crea SIEMPRE el servicio. En error se
  re-renderiza el form conservando las líneas del POST; en éxito, POST-redirect al detalle.
  El ajuste va por modal en `stock.html` (pide cantidad ABSOLUTA + motivo). Los **adjuntos de
  entrada** se validan con `adjuntos.validar_adjunto` (PDF/JPG/PNG ≤10 MB) y se descargan
  SIEMPRE proxiados (`log_entrada_adjunto_descargar`, `?inline=1` abre en pestaña), nunca
  por URL firmada. El ledger global (`log_movimientos`) muestra los últimos 500; el
  histórico completo saldrá por el export de la F6.
- **UI de préstamos (F5):** alta con `PrestamoForm` (cabecera: dirección con texto de ayuda
  dinámico, tercero obligatorio —con alta al vuelo, mismo modal del AJAX de F3—, fecha
  compromiso) + `_lineas_doc.html` con `con_bodega=True` (líneas item+bodega+cantidad,
  parseadas con `parsear_lineas(..., con_bodega=True)`); mismo patrón de re-render en error.
  La **devolución** va por modal en el detalle (`log_prestamo_devolver`, POST con listas
  paralelas `dev_linea_id`/`dev_cantidad` — solo se envían las líneas con pendiente > 0;
  vacío/0 = esa línea no devuelve): NO pide bodega (opera sobre la de cada línea) y el
  estado PARCIAL/CERRADO lo recalcula el servicio. La lista resalta vencidos (ambas
  direcciones) y distingue con badge "Prestamos"/"Nos prestan".
- En `/admin/` todo está registrado; `Movimiento` y `Stock` son **solo lectura**.

## Documentos de profesor (`configuracion.DocumentoProfesor`, tabla `prog_profesores_documentos`)

Adjuntos de la **ficha del profesor** (CV, cédula, RUT, …) gestionados desde la pestaña
**Documentos** del modal "Gestionar" en **Configuración → Profesores** (`configuracion_profesores`).
**Sin límite de cantidad** por profesor; cada archivo guarda historial (`subido_por`/`subido_en`).
Modelo `DocumentoProfesor` (FK→`Profesor` con `on_delete=CASCADE`, `related_name='documentos'`).

- **Subida/listado/borrado por AJAX** (el modal no recarga): `ajax_documentos_profesor` (GET,
  lista JSON), `ajax_subir_documento_profesor` (POST multipart), `ajax_eliminar_documento_profesor`
  (POST). Gate `es_personal_programacion` (`solo_superusuario` en `configuracion.views`).
- **Validación** en `programacion/configuracion/documentos.py:validar_documento` — más permisiva que
  los soportes de pago: admite **PDF, imagen (JPG/PNG) y Office (.doc/.docx/.xls/.xlsx)**, ≤10 MB.
- **Almacenamiento** idéntico a los soportes de pago: `FileField` sobre `STORAGES['default']`
  (disco en dev, Supabase en prod), nombre limpio vía `_documento_profesor_upload_to` →
  `profesores/<slug-profesor>/<slug-archivo><ext>`. **Nunca** se exponen URLs firmadas: la descarga
  la proxia `documento_profesor_descargar` (`FileResponse`, `?inline=1` abre en pestaña, por defecto
  descarga), con el mismo gate de área. Borrar un documento elimina el archivo del storage y la fila.

## Calendario A / B y periodo académico

Cada **`Colegio`** declara su `calendario` (`A`/`B`, default `A`) — propiedad
**invariante** de la institución:

- **Calendario A:** año natural (ene–dic). Es el comportamiento histórico.
- **Calendario B:** el periodo académico **cruza dos años calendario** (ago de `anio` →
  jun de `anio+1`; privados alineados al hemisferio norte).

La ventana real de cada periodo se guarda en **`ColegioAnio.fecha_inicio/fecha_fin`** y
se **autocalcula** en `ColegioAnio.save()` con el helper de módulo
`configuracion.models.periodo_por_defecto(calendario, anio)` (A: 1-ene…31-dic; B:
1-ago…30-jun siguiente). Son editables para ajustes finos por colegio. El entero `anio`
sigue siendo el **ancla = año de inicio** del periodo (`unique_together (colegio, anio)`
intacto: un B "2025"=ago2025–jun2026 no choca con un B "2026").

- **Fuente única del rango:** `ColegioAnio.rango` → `(inicio, fin)` (usa las fechas
  guardadas; si faltan, las calcula). **Todo** lo que delimite el cronograma usa `rango`,
  **no** `date(anio,1,1)/date(anio,12,31)` ni `fecha.year == anio`. Migrados (Fase 3):
  `Clase.clean()` y `Asignacion.save()` (defaults) en `colegios/models.py`; la
  construcción de la matriz (`dashboard_colegios`, `ajax_panel_tabla`), las dos
  validaciones de fecha al guardar clase (`_guardar_clase`, `ajax_guardar_clase`) y la
  clonación de asignaciones en `colegios/views.py`; el `min/max` del datepicker del modal
  "Crear clase" (`dashboard.html`, vía `periodo_inicio/periodo_fin` del contexto). El
  mensaje de fecha-fuera-de-rango usa `periodo_label`. **Clonación y B:** el clon desplaza
  las fechas explícitas por **años relativos** (`delta = nuevo_anio - origen.anio`), no al
  año ancla, para que un periodo B que cruza dos años (fin en jun del año+1) no colapse.
  **Fase 4 (cerrada):** los defaults de filtro de `exportar/views.py` (`_parsear_fechas`,
  GET de `exportar_view`) **se dejan** en ene–dic del año natural a propósito —la
  exportación es un rango libre que cruza varios colegios a la vez, así que no hay una
  única ventana de periodo aplicable; es solo el valor inicial y el usuario lo ajusta.
- **Etiqueta:** `ColegioAnio.periodo_label` → A `"2025"`, B `"2025-2026"`. Úsala en
  selectores/títulos/exports en vez del `anio` crudo. El selector de colegios de la
  exportación (`exportar.html`) la muestra junto al nombre para desambiguar periodos del
  mismo colegio (también la incluye en el `data-nombre` que filtra la búsqueda).
- `Clase` tiene FK directa a `ColegioAnio`, así que las clases ya están **particionadas
  por periodo**; el calendario solo cambia la **ventana** que valida/encuadra cada
  cohorte, no el grafo de datos.
- **UX consciente:** el selector de año del dashboard filtra la lista de colegios por el
  entero `anio`; un B aparece bajo su año-ancla (ej. "2025") con `periodo_label`
  "2025-2026". Un default "periodo que contiene hoy" queda como refinamiento futuro.
- **Dashboard de Colegios/ (`dashboard.html`):** el buscador Select2 lista cada colegio
  como `"<codigo> - <nombre>"` (si tiene código) → busca por código **o** nombre con un
  solo campo. Al seleccionar un periodo, a la izquierda del cronograma se muestra un badge
  "Cal A · `periodo_label`" / "Cal B · `periodo_label`".
- **UI de configuración (`configuracion_colegios`):** al **crear/editar** un colegio se
  elige el calendario (`ColegioForm` incluye `calendario`; selects en el modal Nuevo y en
  el Editar). Al **reclasificar** A↔B, la vista recomputa `fecha_inicio/fecha_fin` de los
  `ColegioAnio` del colegio **que no tengan clases** (`Clase.objects.filter(colegio=ca)`;
  guard para no mover la ventana de un periodo con clases). La lista muestra un badge
  "Cal A"/"Cal B" por colegio y `periodo_label` en los badges de años (tabla + modal
  "Gestionar Años", vía `anios_json`).

## Cancelación de clases por colegio o por profesor (`colegios.CancelacionClase`, tabla `prog_clases_cancelaciones`)

Al marcar "Clase Cancelada" en el modal del dashboard se elige **quién cancela** (radio
`cancelada_por`; default `COLEGIO` para compatibilidad con POSTs sin el campo). La lógica
vive en `_guardar_clase` (`programacion/colegios/views.py`), así cubre la ruta AJAX y la
no-JS, y pasa por la misma invalidación de caché del dashboard:

- **COLEGIO** (comportamiento histórico): `Clase.cancelada=True` (+ motivo en
  `comentarios`) y se crea un registro `CancelacionClase(tipo=COLEGIO)` **vigente**:
  des-cancelar (checkbox off) lo elimina; editar la clase aún cancelada **refresca su
  motivo** (no duplica registro).
- **PROFESOR**: la clase **NO muere** — `cancelada` queda `False`, `profesor=None`
  (pendiente de reasignar; reasignar = edición normal del modal) y se crea un registro
  `tipo=PROFESOR` con **snapshot** del profesor que cancela (el del select del modal, o
  el guardado si el POST no trae profesor). Es **histórico**: NUNCA se borra (ni al
  reasignar; A cancela → reasignan a B → B cancela = 2 registros). Mientras está sin
  profesor no genera fila de pago (`_build_filas_pagos` salta `profesor_id` nulo) y NO
  cuenta como cancelada para la secuencia de unidades (sigue ocupando su unidad: en
  `_guardar_clase` la regularidad usa la cancelación *efectiva*, no el checkbox).
- El registro guarda snapshots (`profesor_nombre`, `colegio_nombre` —FK a `Colegio`, no
  a `ColegioAnio`—, `fecha_clase`, `motivo`, `registrado_por`) → el reporte sobrevive a
  reasignaciones y borrados (todas las FK son SET_NULL; borrar la clase conserva el
  registro). `registrar_cambio` lleva tipo/motivo en el `detalle` del historial.
- **Backfill** (migración `colegios.0019`): cada `Clase` con `cancelada=True`
  preexistente tiene su registro COLEGIO con `registrado_por=None`.

**Reporte "Cancelaciones"** (sidebar → Reportes): `/reportes/cancelaciones/` (names
`reporte_cancelaciones` / `reporte_cancelaciones_excel`), vistas en
`programacion/colegios/views.py` (la app dueña del modelo; no se creó sub-app), gate
`es_personal_programacion`. OJO: la URL cuelga de `/reportes/`, **no** de `/colegios/`
(ese prefijo lo abre el `ControlAccesoMiddleware` a los gestores de colegio; con
`/reportes/` el middleware los bloquea y el gate de vista es la segunda barrera). Tabla
con filtros client-side (tipo, profesor, colegio, motivo + rango sobre `fecha_clase`;
patrón `viaticos/lista.html`) y export a Excel (openpyxl self-contained, modal con
checkboxes de tipo y rango de fechas). Tests en
`programacion/colegios/tests_cancelaciones.py`.

## Enrutado por subdominios y login

**Cada área es un subdominio; el apex es el login.** El urlconf se elige por host:

- [`core/middleware.py`](core/middleware.py) `EnrutadoPorAreaMiddleware`: mira el
  host, fija `request.urlconf` y `request.area`. Subdominio del dominio sin área
  registrada → 404; host ajeno (localhost/IP/healthcheck) → apex.
- [`core/areas.py`](core/areas.py): registro `AREAS` (slug→urlconf+landing) y
  helpers de URL **entre hosts** (`url_en_area`, `url_apex`, `areas_del_usuario`).
  Para añadir un área: regístrala aquí + crea su urlconf + su subdominio en DNS.
- [`core/urls.py`](core/urls.py) (**apex**): `/`→`seleccion_area`, `/panel/`→`panel_admin`
  (panel del superusuario), `/usuarios/`→login, `/admin/`, PWA. **No** monta áreas.
- [`core/urls_programacion.py`](core/urls_programacion.py) y
  [`core/urls_financiera.py`](core/urls_financiera.py) (**áreas**):
  `include('programacion.urls')` / `include('financiera.urls')` en la raíz `/`, +
  `usuarios` (para que `{% url 'logout' %}` resuelva localmente) + PWA.
- [`programacion/urls.py`](programacion/urls.py): el home es el Kanban (`home`) en `/`.
- [`financiera/urls.py`](financiera/urls.py): `''`→`fin_home` (landing) y
  `viaticos/`→`fin_viaticos_lista` + detalle/editar y las acciones POST
  `devolver`/`aprobar`/`pagar` (`fin_viaticos_*`).
- `seleccion_area`/`login_redirect`: resuelven el área del usuario y redirigen a su
  subdominio con URL **absoluta** (helpers de `core/areas.py`). El **superusuario** va
  a `panel_admin` (apex), no al área. Los **usuarios de etiqueta** (grupo
  `area:programacion` o `area:financiera`, sin perfil) caen en `seleccion_area`→si tienen
  una sola área van directo a su landing.
- **Roles dentro del área (4):** superusuario, **staff de área** (grupo
  `area:programacion`, sin perfil → acceso completo igual que superusuario, **incluida**
  la gestión de usuarios de colegio/profesor; **sin** el panel del apex, los usuarios de
  etiqueta, `/admin/` ni otras áreas), gestor colegio, profesor. El predicado de acceso de
  página es `core.areas.es_personal_programacion` (superusuario **o** miembro del grupo);
  se usa en `configuracion.solo_superusuario`, `exportar`, `auditoria.solo_personal`,
  `core.views` (vista_general/historial/búsqueda) y la gestión de usuarios de
  colegio/profesor (`usuarios.views.gestionar_*`/`ajax_*`). `request.es_personal_programacion`
  (lo fija el middleware) controla el menú completo en `base.html`. El staff **no** es
  `is_staff`. El panel y el CRUD de usuarios de etiqueta (`usuarios.views.solo_admin`) y
  las acciones destructivas/borrado siguen gated a `is_superuser`.
- **Contraseñas (dos flujos):**
  - **Colegios/profesores:** el staff de programación **asigna la contraseña a mano** al
    crear y al resetear (ya no es aleatoria). `ajax_crear_usuario`/`ajax_resetear_password`
    leen `password` del POST; el helper `_limpiar_password_temporal` exige **mínimo 8
    caracteres** pero a propósito **no** aplica `AUTH_PASSWORD_VALIDATORS` completos (el
    staff debe poder asignar la clave que quiera; el mínimo existe porque el login es
    público en internet y "1234" se adivina por fuerza bruta aunque haya rate limit).
    No hay cambio forzado ni correo: la clave que escribe el staff es la
    definitiva. `gestionar.html` ya no muestra el modal de "contraseña generada"; hay inputs
    de clave en los modales Crear y Resetear.
  - **Empleados de área** (usuarios de etiqueta): el admin crea el usuario con **clave
    genérica** (manual) + **correo obligatorio** (`User.email`, validado con `validate_email`)
    y se crea un `PerfilEmpleado` (tabla `usuarios_empleados`) con `debe_cambiar_password=True`.
    En el **primer ingreso** el `ControlAccesoMiddleware._redir_cambio_password` redirige a
    `cambiar_password` (vista `cambiar_password_obligatorio`, `SetPasswordForm` → aplica los
    validadores de Django) y bloquea el área hasta que el empleado elija su clave (pone el flag
    en False). El reseteo por el admin (`ajax_resetear_password_area`) vuelve a poner el flag
    True. Hay **auto-servicio "Olvidé mi contraseña"** (enlace en el login) con las vistas
    integradas de Django (`PasswordReset*` en `usuarios/urls.py`, plantillas `usuarios/password_reset*`,
    correo por Resend/SMTP); la subclase `EmpleadoPasswordResetConfirmView` limpia el flag al
    confirmar. El panel del apex (`panel_admin.html`) muestra el correo y permite editarlo
    (`ajax_editar_usuario_area`). Solo los empleados tienen `PerfilEmpleado`, así que
    superusuarios y perfiles colegio/profesor nunca son forzados a cambiar.
- **Área logística:** acceso por grupo `area:logistica` (o superusuario), espejo exacto de
  financiera. Predicado `core.areas.es_personal_logistica`; gate de vistas
  `logistica.inventario.permisos.solo_logistica`; `request.es_personal_logistica` (lo fija el
  middleware) controla el menú en `base_logistica.html`. Sus usuarios de etiqueta se gestionan
  desde el panel del apex (`GRUPOS_ETIQUETA` incluye `logistica`; mismo flujo de empleados con
  `PerfilEmpleado` y cambio de clave forzado). El **inventario** (sub-app
  `logistica.inventario`, label `log_inventario`, tablas `log_*`) se construye por fases;
  hoy existen la landing `log_home`, el dominio completo (modelos + servicios
  transaccionales), la **UI de catálogos** (artículos `log_items_lista`, bodegas/categorías
  bajo `/catalogos/`, terceros con alta AJAX `log_tercero_ajax_crear` para los documentos, y
  existencias `log_stock`) y la **UI de movimientos** (entradas con adjuntos
  `log_entradas_*`/`log_entrada_adjunto_*`, salidas `log_salidas_*` —con alta de tercero al
  vuelo—, traslados `log_traslados_*`, kardex por artículo `log_item_kardex`, ledger global
  `log_movimientos` y ajuste manual `log_ajuste_crear` desde el modal de existencias) y la
  **UI de préstamos** (lista `log_prestamos_lista`, alta `log_prestamos_nuevo` —dirección
  OTORGADO/RECIBIDO, líneas item+bodega+cantidad—, detalle `log_prestamos_detalle` con modal
  de devolución parcial/total `log_prestamo_devolver`); el dashboard, badges y exports llegan
  en la fase 6 (ver sección _Inventario de logística_ abajo). Ver `logistica/README.md`.
- **Área financiera:** acceso por grupo `area:financiera` (o superusuario). Predicado
  `core.areas.es_personal_financiera` (espejo de `es_personal_programacion`); gate de sus
  vistas (`financiera.viaticos.solo_financiera`). `request.es_personal_financiera` (lo fija
  el middleware) controla el menú en `base_financiera.html` (el badge de "Viáticos" =
  solicitudes `ENVIADA` + `LEG_ENVIADA`, vía el context processor
  `financiera.viaticos.context_processors`).
  **Sin** modelos propios: la app importa `SolicitudViatico`/`GastoViatico` de
  `programacion.viaticos` (BD única, mismo patrón que `usuarios`→`configuracion`), y reutiliza
  su form, parseo de gastos y partial `viaticos/_filas_gastos.html`. **Gestión de viáticos:**
  flujo completo de estados (`SolicitudViatico.Estado`):
  `ENVIADA ↔ DEVUELTA → APROBADA → PAGADA → LEG_ENVIADA ↔ LEG_DEVUELTA → FINALIZADA` (terminal).
  Financiera lista/ve y, según la matriz, **devuelve** (con motivo, `ENVIADA→DEVUELTA`),
  **aprueba** (`ENVIADA→APROBADA`), **paga** (`APROBADA→PAGADA`) y **edita** (mientras
  `ENVIADA`/`APROBADA`; `DEVUELTA` es de programación). **Legalización (post-pago):** tras
  `PAGADA`, programación adjunta soportes de legalización (`SoportePago.tipo=LEGALIZACION`,
  vistas `legalizacion_*` en `programacion.viaticos`, permitido en `{PAGADA, LEG_DEVUELTA}`)
  y **envía** (`legalizacion_enviar`, exige ≥1 soporte de legalización → `LEG_ENVIADA`, correo
  a `VIATICOS_LEGALIZACION_NOTIFICAR_A` —default financiero@aamocolombia.com— vía
  `notificar_legalizacion_enviada`); financiera **devuelve la legalización** (con motivo,
  `LEG_ENVIADA→LEG_DEVUELTA`; reutiliza `motivo_devolucion`, se limpia al reenviar) o
  **finaliza** (`LEG_ENVIADA→FINALIZADA`, cierre de expediente). El **soporte de pago**
  (`SoportePago.tipo=PAGO`, default) lo sube/elimina financiera en
  `{PAGADA, LEG_ENVIADA, LEG_DEVUELTA}` (bloqueado en `FINALIZADA`); cada área solo borra
  soportes de su tipo (404 si no). Validación común `.pdf/.jpg/.jpeg/.png` y ≤10 MB.
  Financiera también **exporta a Excel** las solicitudes (modal con filtro de estado —default
  `APROBADA`— y rango de fecha de viaje; openpyxl self-contained en `fin_viaticos_exportar`).
  Asignación al grupo por ahora vía `/admin/`. El menú financiera tiene además **Pagos**
  (ver abajo).
- **Sub-app `programacion.pagos` (label `pagos`):** módulo propio de los pagos semanales a
  profesores. Dueño de los modelos `PagoRealizado` (tabla `prog_pagos`), `SoportePagoProfesor`
  (`prog_pagos_soportes`), `LotePagos` (`prog_pagos_lotes`) y `ExtraPago` (`prog_pagos_extras`).
  Expone los helpers de cálculo compartidos (`construir_contexto_pagos(get, *, modo)`,
  `filas_pagos_por_tab(..., *, modo)`, `_generar_excel_pagos`, `_semana_label`) más los de
  materialización (`_build_filas_pagos`, `_filas_desde_lote`, `preparar_lote_semana`,
  `enviar_lote`). En el menú de programación **Pagos** vive bajo **Reportes**;
  `exportar` queda solo con horarios.
- **Flujo de revisión (programación → financiera), como BACKLOG:** programación **revisa y envía**;
  financiera **solo ve lo enviado** y paga. El estado vive por **semana (`LotePagos`)**:
  `BORRADOR → ENVIADO` (una sola vía; **sin "devolver" y sin "reabrir"** — el envío es definitivo
  **por lote**). Pueden coexistir **N lotes ENVIADO por semana** y **máximo 1 BORRADOR**
  (`UniqueConstraint` parcial `unique_lote_borrador_por_semana`): al enviar, las filas **no
  enviables** (excluidas o con clases **sin informe completado**) se **desacoplan** (`lote=None`) y
  un "Preparar pendientes" posterior las re-adopta a un BORRADOR nuevo → pueden ir en un envío
  posterior; las filas de lotes ENVIADO quedan **congeladas** (ni se adoptan, ni se refrescan, ni se
  borran). El estado `PAGADO` es **por fila** (`PagoRealizado.fecha_pago`, nullable; histórico =
  `lote IS NULL AND fecha_pago IS NOT NULL`). El desglose son los `ExtraPago` (concepto + valor,
  espejo de `GastoViatico`) colgados de la fila base; el total = `valor_base` (= `valor` calculado;
  el campo `valor_base_editado` queda en el modelo pero **ya no se edita por UI**) + extras.
  - **Gate por informe:** una fila solo es enviable si su día `(fecha, profesor, colegio)` tiene
    **todos los informes completados** (`_claves_sin_informe`: clases no canceladas/no evento con
    `informe IS NULL` o `actividades=''`). En programación hay una **tercera pestaña "Sin informe"**
    (entre "Por enviar" y "Enviados") con esas filas: siguen en BORRADOR (permiten excluir/extras)
    pero NO se envían; sirve para recordarle al docente. Al completar el informe pasan a enviables.
    **Financiera: cero cambios** (la pestaña y el radio del export solo existen en programación,
    gated por `tab_label_sin_informe` en los parciales compartidos).
  - **Lista = backlog (todas las semanas)**: `construir_contexto_pagos(get, *, modo)` es **por rango**,
    no por una sola semana. Sin filtro (`semana`/`hasta`) muestra **todo** lo pendiente; el filtro de
    fechas solo acota **al darle Aplicar**. Programación: pestaña *pendiente* = filas por enviar (lote
    BORRADOR con informe, incluye excluidas para re-incluir), *sin_informe* = no enviables por informe,
    *realizado* = ya enviadas; financiera: solo lotes ENVIADO, partidas por `fecha_pago`
    (por pagar / pagadas).
  - **`preparar_pendientes(user)`** materializa el backlog: prepara (idempotente) **todas** las semanas
    con clases hasta hoy (vía `preparar_lote_semana`, que obtiene/crea el **BORRADOR** de la semana,
    la ancla en su lunes–viernes canónico, no pisa override/excluida ni resucita exclusiones, salta
    las filas congeladas en lotes ENVIADO y limpia autogeneradas de clases canceladas); al final
    borra los BORRADOR que quedaron sin filas.
  - **Programación** (`programacion.pagos.views`, gate `es_personal_programacion`, POST+redirect):
    `pagos_preparar` (backlog), `pagos_enviar` (envía **todo lo visible y enviable**: lotes BORRADOR
    con filas no excluidas y con informe dentro del rango filtrado, o todo; `enviar_lote` desacopla
    las no enviables y devuelve False si el lote quedó vacío —sigue BORRADOR—), `pagos_excluir_fila`
    (toggle `excluida`), `pagos_agregar_extra`/`pagos_eliminar_extra`. `pagos.html` tiene la barra
    Preparar/Enviar; por fila un modal **(i) de detalle** (horas, valor/hora, extras, total) y un
    modal de **gestión de costos extra** (agregar/eliminar en el mismo botón); sin editar valor base
    ni reabrir. Las acciones exigen lote `BORRADOR` (`_pago_editable`). Feedback por **toast** (ver
    Mensajes abajo).
- **Pagos a profesores en financiera (`financiera.pagos`, sub-app label `fin_pagos`; sin modelos
  propios, reutiliza los de `programacion.pagos`):** `construir_contexto_pagos(..., modo='financiera')`
  → **solo filas de lotes ENVIADO** (sin las excluidas). `fin_pagos_marcar` opera por **`pago_id`**
  sobre una fila enviada: marcar fija `fecha_pago`/`marcado_por`; desmarcar los limpia y borra los
  soportes (archivos del storage + filas) pero **conserva la fila** (sigue en el lote enviado);
  rechaza filas de lotes no enviados. `fin_pagos_exportar` (Excel del tab, con columna DESGLOSE),
  `fin_pagos_detalle` (datos + desglose + gestión de soportes `SoportePagoProfesor`). En el menú
  financiera **Pagos** es un desplegable con **Profesores** (funcional), **Proyección** (ver abajo)
  y **Monitores** (placeholder).
- **Proyección de pagos (financiera, SOLO LECTURA):** `/pagos/proyeccion/` (names
  `fin_pagos_proyeccion` / `fin_pagos_proyeccion_exportar`, en `financiera.pagos.views`, gate
  `solo_financiera`). Lista las **clases programadas** con su costo estimado (horas × `valor_hora`
  del `ColegioAnio`) para anticipar el gasto: es el cálculo puro de `_build_filas_pagos` (mismas
  exclusiones que los pagos reales: canceladas, eventos, sin profesor) y **NUNCA escribe en BD**
  (no llama `preparar_*` ni crea `LotePagos`/`PagoRealizado`); **no proyecta fecha de pago**
  (decisión del usuario). Filtros server-side por GET: `desde` (default hoy), `hasta` opcional
  (sin `hasta` proyecta todo lo programado, cota `date.max`), `colegio_id` (id de **`ColegioAnio`**,
  el select muestra `periodo_label`) y `profesor_id` — los ids se post-filtran en Python para no
  cambiar la firma del helper compartido. Template `financiera/pagos_proyeccion.html`: aviso
  "no representa pagos preparados ni fechas de pago", filtros por columna + paginación (parciales
  `pagos/_*.html`) y **totales dinámicos client-side** (horas y valor de las filas que pasan el
  filtro, vía `data-horas`/`data-valor`). Export a Excel (`_generar_excel_proyeccion`, openpyxl
  self-contained — sin columnas bancarias ni desglose) con los filtros vigentes (form POST con
  hidden). Sin badge en el menú.
- **Badges de Pagos (COUNT directo, todo el backlog):** financiera
  (`financiera.pagos.context_processors`) = filas **enviadas y no pagadas** (lote ENVIADO,
  `fecha_pago IS NULL`, no excluidas); programación (`programacion.pagos.context_processors`) = filas
  **por enviar** (lote BORRADOR, no excluidas). Las dos vistas comparten el estilo de viáticos (tabla
  con filtros + paginación, modal de exportar) vía los parciales `pagos/_*.html`. El desglose por
  fila se serializa con `json_script` (`detalles_pagos`) para los modales. Asignación al grupo
  `area:financiera` vía `/admin/`.
- **Diagnóstico de errores del navegador (`usuarios.ErrorCliente`, tabla `usuarios_errores_cliente`):**
  capturador **casero** para los errores **intermitentes bajo carga** (el usuario reportó "se cuelga al
  hacer muchas cosas rápido"). Un `<script>` en `base_chrome.html` (justo tras `<body>`, se carga en
  programación y financiera) instala handlers globales (`window.error`, `unhandledrejection`) y un
  **envoltorio de `fetch`** que registra *breadcrumbs* (clics + cada fetch con su status y ms) y, ante
  un error JS / promesa rechazada / fetch fallido (red o HTTP ≥500), hace `POST` con el contexto del
  instante a `telemetria_error_cliente` (`/usuarios/telemetria/error/`, en `usuarios/`, disponible en
  todos los hosts). La vista es **tolerante** (nunca 500: parseo/guardado en try/except, tamaños
  acotados) y guarda `usuario` si está autenticado. La ruta está en `RUTAS_PUBLICAS` del
  `ControlAccesoMiddleware` para capturar desde cualquier rol (incl. colegio/profesor) y sin sesión.
  Por ser pública y anónima está **blindada contra abuso**: `@rate_limit(20/60s)` por IP y topes de
  tamaño también en los campos JSON (`extra`/`breadcrumbs` se descartan si serializados superan
  `_ERR_MAX_JSON_BYTES`; sin esto un anónimo podía insertar ~2.5 MB por request en la BD).
  El login del `/admin/` también tiene rate limit (envuelto en `core/urls.py`, 10/60s por IP);
  `vista_login` y admin responden el 429 en HTML (`respuesta='html'`), el resto en JSON.
  **Caché en prod = Redis (desde jun 2026):** hay un servicio **Redis en Railway** y el servicio
  de la app tiene `CACHE_BACKEND=redis` + `REDIS_URL` (referencia `${{Redis.REDIS_URL}}` → URL
  privada `redis.railway.internal:6379`) → rate limit **global real** entre los 6 workers y caché
  del dashboard compartido e invalidado entre todos (con locmem cada worker tenía su copia y la
  invalidación al guardar/eliminar clase solo aplicaba en el worker que atendió el POST). En
  dev/tests sigue locmem (default sin la env var). **Ojo proxy Railway:** las requests llegan con
  `REMOTE_ADDR` en el rango CGNAT `100.64.0.0/10` (no "privado" para `ipaddress`);
  la IP real del cliente la resuelve `_ip_cliente` (`usuarios/ratelimit.py`). Cadena real en
  prod (verificada empíricamente): usuario → **Cloudflare** (el DNS de `miltonochoa.app` está
  proxied, IPs `104.21.x`/`172.67.x`) → edge de Railway → POP CDN de Railway → app. Railway
  **descarta el XFF entrante y lo reconstruye**: el primer valor es siempre quien se conectó a
  su edge (no falsificable; verificado mandando un XFF falso que no apareció). Como ese peer es
  un nodo de Cloudflare, la IP del usuario solo viaja en **`CF-Connecting-IP`**, que se cree
  únicamente si el primer XFF cae en los rangos publicados de CF (`_RANGOS_CLOUDFLARE`) — quien
  llegue directo a Railway con un `CF-Connecting-IP` inventado es contado por su IP real. Sin
  esto todos los usuarios compartían contador (global con locmem+proxy; por nodo CF después).
  Se consultan en **/admin/** (`ErrorClienteAdmin`, solo lectura). Existe porque los logs de Railway son
  efímeros y `console.log` no sirve para errores intermitentes en producción. (No usa el envoltorio htmx
  porque htmx va por XHR; el dashboard pesado usa `fetch` directo, que sí se instrumenta.)
- **Mensajes (notificaciones):** los `messages` de Django se renderizan como **toast** (abajo-derecha,
  auto-cierre) en `base_chrome.html`, en **programación y logística** (`request.area == 'programacion'
  or request.area == 'logistica'`). En **financiera no aparece ninguna notificación**: el loop de
  `messages` igual los itera (los consume) para que no se acumulen ni se filtren entre subdominios por
  la sesión compartida (SSO). El apex no se toca. **No** dejar bloques `{% if messages %}` en plantillas
  de financiera ni de logística.
- **Soporte de pago (`viaticos.SoportePago` y `pagos.SoportePagoProfesor`):** archivos adjuntos al viático (varios por
  solicitud/pago, con historial: quién subió qué y cuándo). Dos modelos paralelos: `SoportePago`
  (FK→`SolicitudViatico`, tabla `prog_viaticos_soportes`; campo `tipo` `PAGO`/`LEGALIZACION`,
  default `PAGO` — un solo modelo para los dos adjuntos del viático; properties
  `soportes_pago`/`soportes_legalizacion` en `SolicitudViatico` filtran en Python para
  aprovechar el prefetch) y `SoportePagoProfesor`
  (FK→`PagoRealizado`, tabla `prog_pagos_soportes`). El `FileField` usa el backend de
  `STORAGES['default']` (disco en dev, Supabase Storage/S3 en prod) y un nombre limpio vía
  `_soporte_upload_to` → `viaticos/viatico-<slug-docente>-<fecha-viaje><ext>` (viáticos) y
  `_pago_soporte_upload_to` → `pagos/pago-<slug-docente>-<fecha><ext>` (pagos). La validación
  (`.pdf/.jpg/.jpeg/.png`, ≤10 MB) es común: `programacion/viaticos/soportes.py:validar_soporte`.
  **No** se exponen URLs firmadas: la descarga la **proxia** una vista protegida (`_responder_soporte`
  en `programacion.viaticos.views`, vía `archivo.open('rb')` + `FileResponse`), con su gate de
  área por cada flujo (viáticos: `soporte_descargar` @solo_personal / `fin_soporte_descargar`
  @solo_financiera; pagos: `pago_soporte_descargar` @es_personal_programacion /
  `fin_pago_soporte_descargar` @solo_financiera); `?inline=1` abre en pestaña, por defecto
  descarga. Cada área gestiona su tipo y ve el del otro en solo lectura: financiera
  sube/elimina los `tipo=PAGO` (viáticos en `{PAGADA, LEG_ENVIADA, LEG_DEVUELTA}`; pagos en el
  detalle de cualquier pago realizado) y programación los `tipo=LEGALIZACION` (en
  `{PAGADA, LEG_DEVUELTA}`, vistas `legalizacion_*`); en `FINALIZADA` todo queda bloqueado.
  La tarjeta compartida `viaticos/_soportes_card.html` acepta `titulo` opcional (default
  "Soporte de pago") y muestra cada adjunto con `nombre_mostrar` (property de `SoportePago` y
  `SoportePagoProfesor`: el **basename real en storage** —refleja el renombrado del `upload_to`
  y el sufijo único—, no el `nombre_original` subido).
- **SSO:** sesión y CSRF compartidos vía `SESSION_COOKIE_DOMAIN=.BASE_DOMAIN`. Un
  login vale para todos los subdominios.
- `usuarios/middleware.py` (`ControlAcceso`) **solo actúa dentro de un área**
  (`request.area`); en el apex deja pasar (decoradores). **Ramifica por `request.area`:**
  `financiera` → superusuario/grupo `area:financiera` pasan (set `es_personal_financiera`),
  el resto va al selector de área del apex (sin logout); `programacion` mantiene la lógica
  original (superusuario / staff / perfiles colegio-profesor, con prefijos `/colegios/`,
  `/informes/`, `/profesores/`). Sus `reverse` internos pasan `urlconf=request.urlconf`.
- `BASE_DOMAIN` (env): prod `miltonochoa.app`, dev `lvh.me`, tests `testserver`
  (forzado en settings). Plantillas del apex (login, seleccion_area, sin_area)
  extienden **`base_apex.html`**, NO `base.html` (que referencia URLs del área).

## Cómo correr

```bash
# venv en ./venv (Windows: .\venv\Scripts\python.exe)
python manage.py check                       # debe quedar limpio
python manage.py makemigrations --check --dry-run   # no debe proponer migraciones
python manage.py migrate
python manage.py test                        # baseline: 566 tests OK
python manage.py runserver
```

- **Local con SQLite:** crea `.env.dev-api` (se carga antes que `.env`) con
  `DATABASE_URL=sqlite:///db.sqlite3`, `DEBUG=True` y `BASE_DOMAIN=lvh.me`.
  Plantilla en `.env.example`. Abre `http://lvh.me:8000/` (apex) →
  `http://programacion.lvh.me:8000/` (área). `lvh.me` y `*.lvh.me` resuelven a
  127.0.0.1 sin tocar el `hosts`.
- **Tests:** siempre SQLite y `BASE_DOMAIN=testserver` (forzado en `core/settings.py`
  cuando `'test' in sys.argv`). Los tests de área usan
  `Client(HTTP_HOST='programacion.testserver')`; los del apex (login, PWA) el host
  por defecto `testserver`. Los tests que suben archivos **fuerzan disco local**
  (`override_settings(MEDIA_ROOT=<tmp>, STORAGES={...FileSystemStorage...})` +
  `SimpleUploadedFile`, limpiando el tmp en `tearDownClass`) → **nunca** tocan Supabase.

## Almacenamiento de archivos (`STORAGES`)

`core/settings.py` define un único `STORAGES` (Django 5.2 prohíbe mezclarlo con
`STATICFILES_STORAGE`/`DEFAULT_FILE_STORAGE`). El `default` ramifica por la env var
`USE_SUPABASE_STORAGE`:

- **dev / tests** (sin la var, o `False`): `FileSystemStorage` → los archivos caen en
  `MEDIA_ROOT` (`./media/`, ignorado en git).
- **prod** (`True`): `storages.backends.s3.S3Storage` contra el **bucket privado**
  `soportes-pago` de Supabase Storage (path-style, ACL privada, URLs firmadas). Requiere
  las 5 vars `SUPABASE_*` (settings las lee **sin default** → un deploy sin ellas falla al
  arrancar, fail-fast a propósito). `staticfiles` sigue en WhiteNoise (manifest) en prod y se
  fuerza a backend plano en tests (no hay `staticfiles.json`).

Los soportes nunca se sirven por URL pública: se proxian por una vista protegida (ver
`SoportePago` arriba), así el gate de permiso es server-side e idéntico en dev y prod.

## Deuda técnica anotada

- `usuarios/` importa de `programacion.configuracion` (perfiles dependen de
  `Colegio`/`Profesor`). Aceptable mientras `programacion` sea la única área; al
  añadir logistica/financiera hay que generalizar la capa de permisos por área.

## Al contribuir

- Comenta el **porqué** de decisiones no obvias, no el **qué**.
- Si tocas modelos, incluye la migración en el commit.
- Ejecuta `python manage.py test` y compara con el baseline (541 OK).
- Si cambias estructura (rutas, modelos, signals, áreas), **actualiza este archivo y el README**.
- Si cambias estructura, también **regenera el grafo** con `/graphify . --update` para que el
  mapa de `graphify-out/` no quede desfasado (ver la sección _Mapa del proyecto: skill graphify_).

### Flujo de ramas (OBLIGATORIO — se trabaja en varios computadores)

**Nunca** se commitea directo a `dev` ni a `main`. El trabajo siempre va en una **rama
de feature** que luego se mergea por **PR a `dev`**. Esto evita conflictos y pérdidas al
alternar entre máquinas. Pasos antes de empezar cualquier cambio:

1. **Sincroniza `dev` con GitHub primero** (parte siempre de una base actualizada, no de
   una copia vieja del otro computador):
   ```bash
   git checkout dev
   git fetch origin
   git pull --ff-only origin dev        # si falla por divergencia, reconcilia antes de seguir
   ```
2. **Crea una rama** descriptiva según el cambio (`feat/…`, `fix/…`, `docs/…`,
   `refactor/…`), p. ej. `git checkout -b feat/documentos-profesor`.
3. Trabaja, commitea en esa rama y **haz push** (`git push -u origin <rama>`).
4. **Abre un PR hacia `dev`** (`gh pr create --base dev`). El merge a `dev` se hace por PR,
   no a mano. `dev` se promociona a `main` (deploy a Railway) por su propio PR.

- `main` es producción (push a `main` → Railway auto). `dev` es la rama de integración.
- Si ya empezaste a editar sobre `dev` por error y **aún no commiteaste**, no pasa nada:
  crea la rama desde ahí (`git checkout -b <rama>`) y los cambios del working tree se
  llevan a la nueva rama, dejando `dev` limpio.

### Mensajes de commit (evitar el `@` espurio)

Algunos commits del historial salieron con un `@` colado al inicio del subject y
otro al final del body (p. ej. `@ Fix: …`). **Causa:** se pasó una *here-string de
PowerShell* (`@'…'@`) a través de la herramienta **Bash**; bash no entiende esa
sintaxis y mete los `@` literales en el mensaje. Para que los commits queden
prolijos:

- **No mezcles sintaxis de shell.** La here-string `@'…'@` es **solo de
  PowerShell** → úsala únicamente con la herramienta PowerShell. En Bash, usa un
  heredoc normal (`git commit -F- <<'EOF' … EOF`) o un archivo con `git commit -F`.
- El mensaje **debe empezar por la línea de subject** (`Tipo: …`), nunca por `@`.
  Revisa con `git log -1 --format='%s'` que el subject no arranque con `@`.
