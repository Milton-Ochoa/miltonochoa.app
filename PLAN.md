# PLAN — Migración a proyecto unificado **AAMO**

> **Para la sesión de Claude que ejecute esto:** Lee este documento completo antes de tocar nada.
> El objetivo es convertir el proyecto actual `ProgramacionAAMO` en **un solo proyecto Django llamado AAMO**
> que contiene **áreas** en subcarpetas (empezando por `programacion/`, y dejando lista la estructura para
> `logistica/`, `financiera/`, etc.). Un **único login** decide, según permisos del usuario, a qué área redirigir.
>
> **Regla de oro:** el proyecto debe seguir funcionando **exactamente igual** que `ProgramacionAAMO` hoy.
> La prueba de que no rompiste nada es la suite de tests (`python manage.py test`) comparada contra
> `baseline_tests.txt`. No avances de fase si la verificación de la fase anterior falla.

---

## 0. Decisiones ya tomadas con el dueño (NO volver a preguntar)

1. **Arquitectura:** un solo proyecto Django ("un solo edificio"). Un `core/` (motor), un `manage.py`,
   un `venv`, un `requirements`, todo en la raíz `AAMO/`. Las áreas son subcarpetas dentro de `AAMO/`.
2. **Datos y login:** **una sola base de datos** y **un único sistema de login/usuarios** compartido por
   todas las áreas. Al entrar, el sistema mira los permisos del usuario y lo manda a su área.
3. **Alcance de ESTE trabajo:** solo el área **programacion** queda funcionando. La estructura debe quedar
   **lista** para agregar `logistica` y `financiera` después (crear carpetas placeholder, no implementarlas).
4. **Datos iniciales:** arrancar con **base de datos vacía**, y luego cargar el backup que el dueño tiene en
   `C:\Users\Usuario\Desktop\Programacion\AAMO_export.xlsx` (17 hojas con toda la BD). Como el proyecto NO
   trae importador, **hay que crear un comando de importación** (Fase 6).
5. **Fuente del código:** descargar `programacion` **de cero desde GitHub**
   (`https://github.com/MStikMedina/ProgramacionAAMO.git`), **no** copiar de la carpeta local del PC.

---

## 1. Estructura final deseada

```
AAMO/
├── venv/                     # entorno virtual (recrear en Fase 1)
├── manage.py                 # motor Django (apunta a core.settings)
├── README.md                 # del proyecto AAMO (renombrado/actualizado)
├── requirements.txt
├── requirements-dev.txt
├── .env / .env.dev-api       # config local (gitignored; crear plantilla .env.example)
├── PLAN.md                   # este archivo
├── core/                     # MOTOR del proyecto: settings.py, urls.py, wsgi/asgi, views globales
├── usuarios/                 # GLOBAL: login, permisos, middleware de control de acceso
├── templates/                # GLOBALES: base.html, 404/500, login, selector de área, sw.js, manifest
├── static/  staticfiles/     # estáticos globales
├── logs/
├── programacion/             # ÁREA programacion (paquete Python)
│   ├── __init__.py
│   ├── urls.py               # router del área (agrupa todas las sub-apps)
│   ├── configuracion/        # ex-app, con su label interna conservada
│   ├── colegios/
│   ├── profesores/
│   ├── informes/
│   ├── auditoria/
│   ├── exportar/
│   ├── pendientes/
│   ├── api/
│   └── templates/programacion/...   # plantillas específicas del área
├── logistica/                # PLACEHOLDER vacío (solo __init__.py + README) — futuro
└── financiera/               # PLACEHOLDER vacío (solo __init__.py + README) — futuro
```

### Reparto de apps
- **Raíz / globales:** `core` (proyecto), `usuarios` (login y permisos).
- **Área `programacion`:** `configuracion`, `colegios`, `profesores`, `informes`, `auditoria`,
  `exportar`, `pendientes`, `api`.

> Nota técnica: `usuarios` provee el login único, pero sus modelos de perfil (`UsuarioColegio`,
> `UsuarioProfesor`) dependen de `configuracion.Colegio` y `configuracion.Profesor` (ahora dentro de
> `programacion`). Eso obliga a que `usuarios` importe desde `programacion`. Es aceptable por ahora;
> queda anotado como deuda técnica a limpiar cuando se generalice la capa de permisos por área.

---

## 2. Cómo NO romper la base de datos (concepto crítico)

Cuando una app se mueve de `colegios/` a `programacion/colegios/`, su ruta de import en Python cambia.
Pero Django identifica las tablas y migraciones por la **etiqueta** (`app_label`) de la app, **no** por su
ruta. Por defecto la etiqueta es el último tramo de la ruta:

- `colegios`  → label `colegios`
- `programacion.colegios` → label **también** `colegios` (último tramo)

Por lo tanto, si en cada `apps.py` ponemos `name = 'programacion.colegios'` y **dejamos la label en
`colegios`** (es el default, o explícito `label = 'colegios'`), entonces:

- Las migraciones existentes (`colegios/migrations/`) siguen válidas sin tocar.
- Las claves foráneas escritas como string `'configuracion.Colegio'` siguen resolviendo.
- La BD no necesita renombrarse ni recrearse.

**Lo único que cambia de verdad:**
1. Las rutas de `INSTALLED_APPS` (`'colegios'` → `'programacion.colegios'`).
2. Los **imports** de Python (`from colegios.models import X` → `from programacion.colegios.models import X`).
3. Los `include()` de URLs (`include('colegios.urls')` → `include('programacion.colegios.urls')`).
4. El `name` (y `ready()`/signals) de cada `apps.py`.

> **Importante:** los nombres de URL (`{% url 'nombre' %}`) **no** cambian (viven en un namespace global),
> así que las plantillas no se tocan por este motivo. Lo que sí cambia es el **prefijo de las rutas en el
> navegador**: `/colegios/` pasará a `/programacion/colegios/` (ver Fase 5).

---

## FASES

Cada fase tiene: **Objetivo → Pasos → Verificación → Rollback**.
Marca `[x]` al completar y deja una nota corta de resultado al final del archivo (sección "Bitácora").

---

### FASE 0 — Preparación y red de seguridad
**Objetivo:** tener respaldos y la "foto" de referencia antes de mover nada.

**Pasos:**
1. Confirmar que existe `C:\Users\Usuario\Desktop\Programacion\AAMO_export.xlsx`. Copiarlo a
   `AAMO/backups/AAMO_export.xlsx` (crear carpeta si no existe). NO trabajar sobre el original.
2. Guardar copia de referencia de los baselines del proyecto viejo (están en
   `..\ProgramacionAAMO\baseline_tests.txt` y `baseline_tablas.txt`) dentro de `AAMO/` para comparar al final.
3. Verificar versión de Python disponible: `python --version` (debe ser 3.11+).

**Verificación:** los archivos de respaldo existen en `AAMO/backups/` y `AAMO/`.

**Rollback:** ninguno (solo lectura/copia).

---

### FASE 1 — Traer el código desde GitHub y montar el esqueleto AAMO
**Objetivo:** clonar `ProgramacionAAMO` fresco y colocar el motor en la raíz de `AAMO/`.

**Pasos:**
1. Clonar el repo en una carpeta temporal **dentro** de AAMO:
   `git clone https://github.com/MStikMedina/ProgramacionAAMO.git _tmp_programacion`
   (Si falla por red/credenciales, detenerse y avisar al dueño; NO copiar del PC local salvo que él lo autorice).
2. Mover el **motor y archivos globales** del clon a la raíz `AAMO/`:
   - `manage.py`, `core/`, `requirements.txt`, `requirements-dev.txt`, `README.md`, `templates/`, `usuarios/`,
     `static/` (si existe), `.gitignore`, y cualquier `pytest.ini/conftest.py` si los hubiera.
3. Crear el entorno virtual nuevo en `AAMO/venv` e instalar dependencias:
   - `python -m venv venv`
   - `.\venv\Scripts\python -m pip install -r requirements.txt -r requirements-dev.txt`
   - (El `venv` viejo NO se copia; se recrea desde cero como pidió el dueño).
4. Crear `.env.dev-api` local apuntando a **SQLite** para poder verificar sin tocar producción
   (revisar cómo lo lee `core/settings.py`: usa `dj_database_url` con `DATABASE_URL`; para SQLite local
   usar algo como `DATABASE_URL=sqlite:///db.sqlite3` y `DEBUG=True`). Crear también `.env.example` documentado.

**Verificación:** `\.venv\Scripts\python manage.py check` corre sin errores fatales (todavía con las apps
en su sitio original dentro del clon temporal — ver nota). Si en este punto el motor ya está en la raíz pero
las apps siguen en `_tmp_programacion`, el `check` fallará por imports; está bien, se resuelve en Fase 2.

**Rollback:** borrar `_tmp_programacion`, `venv`, y los archivos movidos; reintentar el clon.

---

### FASE 2 — Crear el paquete `programacion/` y mover las apps del área
**Objetivo:** dejar todas las apps del área dentro de `AAMO/programacion/` conservando sus labels.

**Pasos:**
1. Crear `AAMO/programacion/__init__.py` (paquete vacío).
2. Mover desde el clon a `programacion/` estas apps (carpetas completas, incluidas `migrations/` y `templates/`):
   `configuracion`, `colegios`, `profesores`, `informes`, `auditoria`, `exportar`, `pendientes`, `api`.
3. En cada `apps.py` de esas apps: cambiar `name = 'X'` → `name = 'programacion.X'` y añadir `label = 'X'`
   (explícito, para blindar contra cambios futuros). Ajustar imports internos en `ready()`
   (p.ej. `import colegios.signals` → `import programacion.colegios.signals`).
4. Mover plantillas específicas del área a `programacion/templates/programacion/` si conviene, o dejarlas en
   `programacion/<app>/templates/` (APP_DIRS=True las encuentra igual). Las **globales**
   (`base.html`, `404.html`, `500.html`, `home.html`, `sw.js`, login) quedan en `AAMO/templates/`.
5. Borrar la carpeta temporal `_tmp_programacion`.

**Verificación:** la estructura de carpetas coincide con la sección 1. Aún NO se espera que `check` pase
(faltan imports y settings → Fases 3 y 4).

**Rollback:** restaurar desde el clon temporal (no borrarlo hasta terminar Fase 5 con éxito).
Sugerencia: hacer commit de git en cada fase para poder revertir con `git`.

---

### FASE 3 — Reescribir imports y referencias de Python
**Objetivo:** que todos los `import` apunten a las nuevas rutas `programacion.<app>`.

**Pasos:**
1. Reemplazo sistemático en **todo** el árbol (excluyendo `venv/`, `migrations/` de terceros) de los imports
   absolutos de las apps movidas. Para cada app del área (`configuracion`, `colegios`, `profesores`,
   `informes`, `auditoria`, `exportar`, `pendientes`, `api`):
   - `from <app>` → `from programacion.<app>`
   - `import <app>` → `import programacion.<app>`
   - cadenas `include('<app>.urls')` → `include('programacion.<app>.urls')`
   - **Cuidado:** NO tocar `app_label` en cadenas de FK como `'configuracion.Colegio'` (la label sigue
     siendo `configuracion`). NO tocar nombres de URL en `{% url %}`. NO renombrar dentro de archivos de
     `migrations/` (referencian por label, ya válidos).
2. Revisar especialmente: `usuarios/` (importa `from configuracion.models import Colegio, Profesor`),
   `usuarios/middleware.py`, `core/urls.py`, `core/views.py`, y los `signals.py`.
3. Buscar imports relativos rotos y cualquier `apps.get_model('app', 'Model')` (esos usan label → no cambian).

**Verificación:** `python manage.py check` pasa **sin errores**. Si hay `ImportError`, corregir hasta que
`check` quede limpio.

**Rollback:** `git checkout` de los archivos afectados.

---

### FASE 4 — Ajustar `core/settings.py`
**Objetivo:** registrar las apps en su nueva ruta y dejar la config coherente.

**Pasos:**
1. En `INSTALLED_APPS`: cambiar las 8 apps del área a `'programacion.configuracion'`, `'programacion.colegios'`,
   … `'programacion.api'`. Dejar `core` y `usuarios` como están. (Opcional: añadir un `'programacion'` solo si
   se le crea un `apps.py`; normalmente no hace falta.)
2. `TEMPLATES['DIRS']` ya apunta a `BASE_DIR / 'templates'` (globales). Verificar que las plantillas de área
   se siguen resolviendo vía `APP_DIRS`.
3. Confirmar rutas de `STATIC_ROOT`, `LOG_DIR`, backups (`BASE_DIR.parent / 'backups'` → revisar si conviene
   cambiarlo a `BASE_DIR / 'backups'` ahora que la estructura cambió).
4. Verificar `ROOT_URLCONF = 'core.urls'`, `WSGI_APPLICATION`, `LOGIN_URL` (apunta a la ruta de login;
   se ajustará el prefijo en Fase 5).

**Verificación:** `python manage.py check` sigue limpio. `python manage.py makemigrations --check --dry-run`
**no** debe proponer migraciones nuevas (si propone, es señal de que alguna label cambió sin querer →
investigar antes de seguir).

**Rollback:** `git checkout core/settings.py`.

---

### FASE 5 — Enrutado por áreas y login único
**Objetivo:** un punto de entrada que, según permisos, lleve a cada área. Programacion bajo `/programacion/`.

**Pasos:**
1. Crear `programacion/urls.py` que agrupe las rutas del área (lo que antes estaba en `core/urls.py`):
   `configuracion/`, `colegios/`, `profesores/`, `general/`, `informes/`, `auditoria/`, `exportar/`,
   `historial/`, `buscar/`, `pendientes/`, `api/v1/`, y el `home` del área (`kanban_inicio`).
2. Reescribir `core/urls.py` para que sea el router AAMO:
   ```
   path('', seleccion_area, name='home')          # decide a dónde mandar al usuario logueado
   path('admin/', admin.site.urls)
   path('programacion/', include('programacion.urls'))
   path('manifest.json', manifest_view) ; path('sw.js', sw_view)   # PWA, globales
   # login/usuarios: mantener la ruta de login global (ver punto 4)
   ```
3. Crear la vista `seleccion_area` (en `core/views.py` o un nuevo módulo): si el usuario tiene acceso a una
   sola área, **redirige** directo; si tiene varias, muestra una página simple de selección; si no tiene
   ninguna, mensaje claro. Para representar el acceso por área usar **grupos de Django** (p.ej. grupo
   `area:programacion`) o un permiso dedicado — elegir lo más simple y dejarlo documentado para escalar a
   logistica/financiera.
4. Login único: mantener el login actual de `usuarios`/`configuracion` como entrada global. Ajustar
   `LOGIN_URL` y los `redirect` post-login para que pasen por `seleccion_area`.
5. Verificar que `kanban_inicio` (antes `home` en `/`) ahora vive en `/programacion/`.
6. Crear placeholders `logistica/__init__.py` + `logistica/README.md` y `financiera/__init__.py` +
   `financiera/README.md` explicando que son áreas futuras (sin rutas activas todavía).

**Verificación:**
- `python manage.py check` limpio.
- Arrancar servidor (`python manage.py runserver`) con BD SQLite vacía + migraciones aplicadas
  (`migrate`) + un superusuario de prueba: el login funciona y, tras entrar, redirige a `/programacion/`.
- Navegar manualmente: colegios, profesores, informes, exportar, pendientes responden (aunque sin datos).

**Rollback:** `git checkout core/urls.py programacion/urls.py core/views.py`.

---

### FASE 6 — Importador del backup Excel
**Objetivo:** poder cargar `AAMO_export.xlsx` en la BD vacía para verificar con datos reales.

**Contexto:** el Excel tiene 17 hojas: `Usuarios`, `Profesores`, `Materias`, `Colegios`, `ColegioAnio`,
`Grados`, `NombreLibro`, `Unidades`, `Bloques`, `Asignaciones`, `ClasesParticulares`, `Informes`, `Tareas`,
`AlertasAuditoria`, `HistorialCambios`, `UsuarioColegio`, `UsuarioProfesor`.
El proyecto **no** trae importador (solo exporta horarios), así que se construye uno.

**Pasos:**
1. Crear un management command, p.ej. `programacion/configuracion/management/commands/importar_backup.py`
   (o en `core/` si se prefiere global), invocable como
   `python manage.py importar_backup backups/AAMO_export.xlsx`.
2. Antes de escribir el código, **inspeccionar las columnas** de cada hoja con `openpyxl` y mapearlas a los
   campos de cada modelo. Confirmar los modelos reales:
   - `Usuarios` → `auth.User` (y password: si el Excel trae hash, setearlo directo; si no, usar
     `set_unusable_password()` o una contraseña temporal documentada).
   - `Profesores`, `Materias`, `Colegios`, `ColegioAnio`, `Grados`, `NombreLibro`, `Unidades` → app
     `configuracion` (`Profesor`, `NombreLibro`, `Unidad`, `ColegioAnio`, etc.).
   - `Bloques`, `Asignaciones`, `ClasesParticulares` → app `colegios` (`Bloque`, `Asignacion`,
     `ClaseParticular`, `Clase`).
   - `Informes` → app `informes`.
   - `Tareas` → app `pendientes`.
   - `AlertasAuditoria`, `HistorialCambios` → app `auditoria`.
   - `UsuarioColegio`, `UsuarioProfesor` → app `usuarios`.
3. Cargar en **orden de dependencias** (primero usuarios y catálogos, luego lo que referencia a otros), dentro
   de una **transacción atómica**. Manejar claves foráneas por id o por nombre según traiga el Excel.
   Hacer el comando **idempotente** si es viable (`update_or_create`) para poder re-ejecutarlo.
4. Si alguna hoja no calza con el modelo actual (el backup pudo generarse con un esquema previo), **detenerse
   y reportar** las diferencias al dueño en vez de inventar datos.

**Verificación:**
- `python manage.py migrate` sobre SQLite limpio, luego `python manage.py importar_backup backups/AAMO_export.xlsx`.
- Contar filas por tabla y comparar con las hojas del Excel (Profesores≈81 datos, Colegios≈28, Unidades≈183,
  Bloques≈120, Asignaciones≈64, HistorialCambios≈1557, etc. — restando la fila de encabezado).
- Arrancar el servidor y comprobar visualmente que colegios/profesores/horarios muestran datos.

**Rollback:** borrar `db.sqlite3` y re-`migrate` (datos de prueba, sin riesgo).

---

### FASE 7 — Verificación final ("funciona igual que antes")
**Objetivo:** demostrar con evidencia que AAMO se comporta como `ProgramacionAAMO`.

**Pasos:**
1. Correr la suite completa: `python manage.py test 2>&1 | Tee-Object resultado_tests_AAMO.txt`.
2. Comparar contra `baseline_tests.txt` (mismo nº de tests, mismos OK/errores esperados). Cualquier test que
   antes pasaba y ahora falla es un bloqueante → arreglar.
3. Comprobar tablas: `python manage.py migrate --check` y revisar que el set de tablas coincide con
   `baseline_tablas.txt` (las labels no cambiaron, así que deben ser idénticas).
4. Humo manual: login → redirección a área → navegación por las secciones principales → exportar un Excel de
   horario → revisar auditoría/pendientes.
5. Actualizar `README.md` y `CLAUDE.md` para describir la nueva estructura AAMO (áreas, login único, cómo
   correr local con SQLite, cómo importar el backup).

**Verificación:** tests al mismo nivel que el baseline + humo manual OK.

**Entregable (lo que el dueño pidió):** al terminar, dar un **resumen de todo lo realizado** y la
**comprobación** de que el proyecto funciona igual que `ProgramacionAAMO` (adjuntar conteo de tests y
captura/numérico de datos cargados).

---

## 3. Riesgos y cómo mitigarlos
- **Reescritura masiva de imports (Fase 3):** es lo más propenso a error. Mitigación: usar `manage.py check`
  como semáforo y commits de git por fase para revertir rápido.
- **Backup Excel con esquema antiguo (Fase 6):** puede no calzar 1:1 con los modelos actuales. Mitigación:
  inspeccionar columnas primero y reportar diferencias antes de cargar.
- **Cambio de prefijos de URL (`/colegios/` → `/programacion/colegios/`):** si hubiera URLs escritas a mano
  (no vía `{% url %}`) se romperían. Mitigación: buscar literales de ruta en plantillas/JS.
- **Acoplamiento `usuarios` → `programacion`:** aceptable ahora; anotar como deuda técnica para cuando se
  generalice la capa de permisos por área (al añadir logistica/financiera).

## 4. Trabajo explícitamente FUERA de alcance ahora
- Implementar `logistica` y `financiera` (solo placeholders).
- Fusionar `LogisticaAAMO` (proyecto aparte) dentro de AAMO.
- Despliegue en producción / cambios de infraestructura (Render, Postgres). Se verifica en local con SQLite.

---

## 5. Bitácora de ejecución (la rellena la sesión que ejecuta)
- [x] Fase 0 — Respaldos OK: `backups/AAMO_export.xlsx` (178 KB) y baselines copiados a la raíz. Baseline: 167 tests OK, 32 tablas. Python 3.13.13, git 2.54.
- [x] Fase 1 — Clon OK (commit a296127). Motor+globales (manage.py, core/, usuarios/, templates/, requirements, README, .gitignore) en raíz. venv recreado e instalado (Django 5.2.11). Creados `.env.dev-api` (SQLite) y `.env.example`. `check` falla con `No module named 'configuracion'` (esperado: apps aún en _tmp). git init para rollback.
- [ ] Fase 2 —
- [ ] Fase 3 —
- [ ] Fase 4 —
- [ ] Fase 5 —
- [ ] Fase 6 —
- [ ] Fase 7 —
