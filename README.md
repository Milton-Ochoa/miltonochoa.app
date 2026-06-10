<div align="center">

<img src="https://img.shields.io/badge/AAMO-Plataforma-212529?style=for-the-badge&labelColor=0d6efd" alt="AAMO"/>

# AAMO

### Plataforma web multi-área para la organización educativa **Milton Ochoa / AAMO**

*Un solo proyecto Django, un solo login. Cada **área** del negocio vive en su propio **subdominio**, sobre una única base de datos.*

<br/>

[![Django](https://img.shields.io/badge/Django-5.2.11-092E20?style=flat&logo=django&logoColor=white)](https://www.djangoproject.com/)
[![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Supabase-336791?style=flat&logo=postgresql&logoColor=white)](https://supabase.com/)
[![HTMX](https://img.shields.io/badge/HTMX-1.9-3D72D7?style=flat&logo=htmx&logoColor=white)](https://htmx.org/)
[![Bootstrap](https://img.shields.io/badge/Bootstrap-5.3-7952B3?style=flat&logo=bootstrap&logoColor=white)](https://getbootstrap.com/)
[![PWA](https://img.shields.io/badge/PWA-ready-5A0FC8?style=flat&logo=pwa&logoColor=white)](https://web.dev/progressive-web-apps/)
[![Railway](https://img.shields.io/badge/Deploy-Railway-0B0D0E?style=flat&logo=railway&logoColor=white)](https://railway.app/)
[![License](https://img.shields.io/badge/Uso-Interno-lightgrey?style=flat)](#-licencia)

</div>

---

## Tabla de contenidos

- [Visión general](#-visión-general)
- [Áreas de la plataforma](#-áreas-de-la-plataforma)
- [Arquitectura multi-área](#️-arquitectura-multi-área)
- [Área Programación](#-área-programación)
- [Área Financiera](#-área-financiera)
- [Stack tecnológico](#️-stack-tecnológico)
- [Estructura del proyecto](#️-estructura-del-proyecto)
- [Roles y control de acceso](#-roles-y-control-de-acceso)
- [Instalación local](#-instalación-local)
- [Variables de entorno](#️-variables-de-entorno)
- [Tests y calidad](#-tests-y-calidad)
- [Despliegue en producción](#️-despliegue-en-producción)
- [Añadir una nueva área](#-añadir-una-nueva-área)
- [Mantenimiento](#-mantenimiento)
- [Contribuir](#-contribuir)
- [Licencia](#-licencia)

---

## Visión general

**AAMO** es la plataforma web interna de la organización educativa **Milton Ochoa / AAMO**.
Está construida como **un único proyecto Django** organizado por **áreas** de negocio
(programación académica, financiera, logística…), donde:

- **Un solo edificio, varias áreas.** Todo vive en el mismo proyecto y comparte
  una **única base de datos** y un **único sistema de usuarios**.
- **Cada área es un subdominio.** El **apex** (`miltonochoa.app`) es el login único
  y el selector de área; cada área se sirve en su propio host
  (`programacion.miltonochoa.app`, `financiera.miltonochoa.app`).
- **Un solo login (SSO).** El usuario se autentica una vez en el apex y, según sus
  permisos, es redirigido al subdominio de su área. La sesión se comparte entre todos
  los subdominios vía `SESSION_COOKIE_DOMAIN`.
- **Crece por áreas.** Añadir un área nueva es registrar su `urlconf` y su subdominio;
  el motor de enrutado del `core/` hace el resto.

> **Idioma:** Español (Colombia) · **Zona horaria:** America/Bogota · **Moneda:** COP  
> **Dominio:** `miltonochoa.app` (dev: `lvh.me`)

---

## Áreas de la plataforma

| Área | Subdominio | Estado | Qué hace |
|------|------------|:------:|----------|
| **Apex** | `miltonochoa.app` | Activa | Login único, selector de área y **panel del superusuario** (`/panel/`). |
| **Programación** | `programacion.miltonochoa.app` | Activa | Gestión académica integral: calendario, auditoría, informes, pagos semanales a profesores y viáticos. |
| **Financiera** | `financiera.miltonochoa.app` | Activa | Gestión de **viáticos** (devolver / aprobar / pagar / legalización / finalizar + soportes) y **pagos a profesores** (marcar pago + soportes + Excel), con badge de pendientes. Acceso por grupo `area:financiera`. |
| **Logística** | `logistica.miltonochoa.app` | Placeholder | Reservada. Paquete creado, sin apps ni rutas todavía. |

**Programación** y **Financiera** comparten el mismo *chrome* visual (sidebar, header, footer)
definido en `templates/base_chrome.html`; cada área solo aporta su menú y títulos propios.

---

## Arquitectura multi-área

El corazón de AAMO es el **enrutado por subdominio**: el mismo proyecto Django responde en
todos los hosts, y un middleware elige qué `urlconf` montar según el subdominio de la petición.

```
                         Cliente (navegador / PWA)
                                     │  HTTP(S)
        ┌────────────────────────────┼────────────────────────────┐
        │                            │                            │
        ▼                            ▼                            ▼
 miltonochoa.app          programacion.miltonochoa.app    financiera.miltonochoa.app
   (APEX)                      (ÁREA programacion)          (ÁREA financiera)
        │                            │                            │
        └────────────────────────────┴────────────────────────────┘
                                     │
            ┌────────────────────────▼───────────────────────────┐
            │  core.middleware.EnrutadoPorAreaMiddleware         │
            │  Mira el host → fija request.urlconf y request.area│
            │   · apex            → core.urls                    │
            │   · <area>.dominio  → urlconf del área (core.areas)│
            │   · subdominio sin área registrada → 404           │
            └────────────────────────┬───────────────────────────┘
                                     │
            ┌────────────────────────▼─────────────────────────┐
            │  usuarios.middleware.ControlAcceso               │
            │  Solo dentro de un área: login + scope por rol   │
            │  + inyecta el perfil en request                  │
            └────────────────────────┬─────────────────────────┘
                                     │
   ┌──────────────────┬──────────────┼───────────────────┬──────────────────┐
   ▼                  ▼              ▼                   ▼                  ▼
Vistas HTMX    Comandos manage   Caché (locmem)    Login/SSO         PWA (manifest+sw)
   │                  │              │                   │                  │
   └──────────────────┴──────────────┴───────────────────┴──────────────────┘
                                     │
            ┌────────────────────────▼─────────────────────────┐
            │   ORM Django · Signals · Caché (locmem/Redis)    │
            └────────────────────────┬─────────────────────────┘
                                     │
   PostgreSQL (Supabase, producción)              SQLite (local / tests)
```

**Piezas clave (todas en `core/`):**

| Pieza | Rol |
|-------|-----|
| [`core/middleware.py`](core/middleware.py) | `EnrutadoPorAreaMiddleware`: elige `urlconf` y fija `request.area` según el host. Host ajeno (localhost/IP/healthcheck) → apex. |
| [`core/areas.py`](core/areas.py) | Registro único `AREAS` (slug → urlconf + landing) y helpers de URL **entre hosts** (`url_en_area`, `url_apex`, `areas_del_usuario`). |
| [`core/urls.py`](core/urls.py) | **Apex**: `/` → selector de área, `/panel/` → panel del superusuario, `/usuarios/` → login, `/admin/`, PWA. |
| [`core/urls_programacion.py`](core/urls_programacion.py) | **Área programación**: monta `programacion.urls` en la raíz `/` + login local + PWA. |
| [`core/urls_financiera.py`](core/urls_financiera.py) | **Área financiera**: monta `financiera.urls` en la raíz `/` + login local + PWA. |

> **SSO entre subdominios:** la sesión y el CSRF se comparten vía
> `SESSION_COOKIE_DOMAIN=.BASE_DOMAIN`. Un único login vale para todos los subdominios.

---

## Área Programación

El área **Programación** (`programacion.miltonochoa.app`) gestiona la programación académica
de extremo a extremo. Es un paquete Python (`programacion/`) que agrupa **9 sub-apps**.

### Programación visual

- **Vista general**: calendario unificado de todos los colegios activos, agrupado por
  colegio → grado → bloque, con caché HTML por mes (10 min).
- **Dashboard por colegio**: matriz `grado × fecha` editable inline con HTMX, con recálculo
  automático de secuencia al mover clases. Badge de calendario A/B y periodo label.
- **Recomendación inteligente** de la siguiente unidad al programar, considerando libro
  asignado, fecha y socializaciones.
- **Clases particulares** fuera del horario regular.

### Catálogo modular

- **Colegio ↔ Colegio-Año**: separa datos invariantes (nombre, ciudad, **calendario A/B**…)
  de los anuales (tarifa por hora, activo/inactivo, **ventana del periodo**) → historial
  sin duplicar registros.
- **Calendario A / B**: cada colegio funciona en año natural (**A**: ene–dic) o en un
  periodo que cruza dos años (**B**: ago → jun siguiente, típico de colegios privados).
  El cronograma, las validaciones de fecha y las etiquetas respetan la ventana real del
  periodo (`ColegioAnio.rango`), no el año calendario.
- **Libros normales vs. material asignado**: dos categorías con flujos distintos.
- **Asignaciones por rango de fechas**: un grado puede cambiar de libro a mitad de año.

### Auditoría automática

| Tipo de alerta | Detecta |
|----------------|---------|
| **Duplicado** | Misma unidad de la misma materia programada más de una vez en `(colegio, grado, libro)` |
| **Conflicto** | Un profesor con clases en más de un colegio el mismo día |
| **Secuencia** | Salto en la numeración de unidades (ej. pasó de 2 a 4) |

- Deduplicación por **hash MD5** → no se crean alertas repetidas.
- Reactivación automática si un error reaparece (salvo que se haya ignorado manualmente).
- Throttle de 5 minutos para evitar barridos concurrentes.
- Comando de cron: `python manage.py ejecutar_auditoria`.

### Informes pedagógicos

- Un `Informe` está vinculado a **exactamente una** clase regular o particular (garantizado
  por `CheckConstraint` a nivel BD).
- Datos de cabecera desnormalizados para sobrevivir si se elimina la clase original.
- Estados: borrador → completado (al rellenar `actividades`).
- **Diligenciable desde dos lugares** con el mismo modal compartido: el cronograma del
  profesor y la **lista de informes** (botón por fila que precarga el informe vía AJAX;
  al guardar, la lista se recarga ya actualizada). Si quien guarda es un perfil de
  profesor, el servidor ignora cualquier `profesor_id` del payload y usa el del perfil.

### Portal del profesor

Los usuarios con perfil de profesor (`UsuarioProfesor`) tienen un **menú propio** en el
sidebar con tres ítems:

- **Cronograma** — su horario personal (la vista fuerza su propio profesor).
- **Informes** — su lista de informes/pendientes, con diligenciamiento desde la fila.
- **Pagos** — estado de sus pagos por día de clases, en dos pestañas (*Pendientes por
  pagar* / *Pagadas*) con fecha, colegio y horas. En las pagadas muestra la fecha de pago
  y permite **ver/descargar el soporte** (gateado al dueño: el soporte de otro profesor
  responde 404). **Nunca muestra montos en pesos** — solo estado y comprobante.

### Liquidación de pagos semanales

- Cálculo `horas × ColegioAnio.valor_hora` por profesor / colegio / fecha.
- **Flujo borrador → enviado (una sola vía):** programación **prepara** el borrador semanal
  (`LotePagos` BORRADOR), **excluye filas**, **agrega costos extra** (`ExtraPago`) y luego
  **envía a financiera** (BORRADOR→ENVIADO). El envío es definitivo **por lote**, pero las
  filas excluidas o retenidas no mueren con él: se desacoplan y pueden ir en un envío
  posterior (varios lotes enviados por semana; máximo un borrador).
- **Gate por informe:** una fila solo se envía si todas las clases de su día tienen el
  informe pedagógico completado. Las retenidas se listan en la pestaña **"Sin informe"**
  (con badge por fila) para recordarle al docente; al completar el informe pasan a enviables.
- Total = valor base + extras (desglose).
- El backlog muestra todas las semanas pendientes; el filtro de fechas solo acota al aplicar.

### Viáticos

- Solicitudes de viáticos con datos del docente, fechas, gastos desglosados (`GastoViatico`)
  y notificación por correo al área financiera al enviar.
- Flujo de estados completo:
  `ENVIADA ↔ DEVUELTA → APROBADA → PAGADA → LEG_ENVIADA ↔ LEG_DEVUELTA → FINALIZADA`.
- Los soportes de pago (`SoportePago`, tipo `PAGO`) los adjunta financiera desde `PAGADA`.
- **Legalización post-pago:** tras `PAGADA`, programación adjunta soportes de legalización
  (`SoportePago`, tipo `LEGALIZACION`) y los envía a financiera (requiere ≥1 soporte; avisa
  por correo). Financiera los revisa y devuelve con motivo o **finaliza** la solicitud
  (cierre definitivo del expediente).

### Exportación Excel

- Generación 100 % en memoria con **openpyxl** (sin tocar disco — ideal para Railway).
- ZIPs masivos (un Excel por profesor o por colegio).
- Días/meses siempre en español, independiente del locale del SO.

### Tablero Kanban (home del área)

Pendientes con tres columnas (Pendiente · En gestión · Completado), operable con HTMX.

---

## Área Financiera

El área **Financiera** (`financiera.miltonochoa.app`) no tiene modelos propios: importa los de
`programacion.viaticos` y `programacion.pagos` (BD única compartida). Acceso por grupo
`area:financiera`.

### Gestión de viáticos

Financiera **solo ve lo enviado** por programación. Según el estado puede:

| Acción | Estado requerido | Estado resultante |
|--------|-----------------|-------------------|
| Devolver (con motivo) | `ENVIADA` | `DEVUELTA` |
| Aprobar | `ENVIADA` | `APROBADA` |
| Pagar | `APROBADA` | `PAGADA` |
| Editar | `ENVIADA` o `APROBADA` | — |
| Subir/eliminar soporte de pago | `PAGADA`, `LEG_ENVIADA` o `LEG_DEVUELTA` | — |
| Devolver legalización (con motivo) | `LEG_ENVIADA` | `LEG_DEVUELTA` |
| Finalizar | `LEG_ENVIADA` | `FINALIZADA` (terminal) |
| Exportar a Excel | cualquier estado | — |

Los soportes de **legalización** los gestiona programación (financiera los ve en solo
lectura). El badge del menú cuenta `ENVIADA` + `LEG_ENVIADA`.

### Pagos a profesores

- Ve **solo las semanas enviadas** (lotes `ENVIADO`) con su desglose de extras.
- Marca el pago por fila (`fecha_pago`, `marcado_por`); desmarcar limpia el pago y sus soportes
  pero conserva la fila.
- Sube/elimina comprobantes (`SoportePagoProfesor`: `.pdf/.jpg/.jpeg/.png`, ≤ 10 MB).
- Exporta a Excel por tab (por pagar / pagadas), con columna de desglose.
- Badge en el menú: filas enviadas y no pagadas.

---

## Stack tecnológico

<table>
<tr><th>Capa</th><th>Tecnología</th><th>Versión</th></tr>
<tr><td>Backend</td><td>Django</td><td>5.2.11</td></tr>
<tr><td>Runtime</td><td>Python</td><td>3.13 (fijado en <code>.python-version</code>)</td></tr>
<tr><td>Interactividad</td><td>HTMX + django-htmx</td><td>1.9 / 1.19.0</td></tr>
<tr><td>UI</td><td>Bootstrap + Font Awesome</td><td>5.3 / 6.0 (CDN)</td></tr>
<tr><td>BD producción</td><td>PostgreSQL (Supabase pooler)</td><td>—</td></tr>
<tr><td>BD tests/local</td><td>SQLite</td><td>auto</td></tr>
<tr><td>Caché</td><td>locmem (default) · django-redis (opt)</td><td>5.4.0</td></tr>
<tr><td>Estáticos</td><td>WhiteNoise (gzip + manifest)</td><td>6.12.0</td></tr>
<tr><td>Excel</td><td>openpyxl</td><td>3.1.5</td></tr>
<tr><td>Almacenamiento archivos</td><td>FileSystem (dev) · Supabase Storage/S3 (prod)</td><td>django-storages 1.14.4</td></tr>
<tr><td>WSGI prod</td><td>gunicorn</td><td>25.3.0</td></tr>
<tr><td>PaaS</td><td>Railway (deploy desde <code>main</code>)</td><td>—</td></tr>
<tr><td>BD gestionada</td><td>Supabase (PostgreSQL)</td><td>—</td></tr>
</table>

---

## Estructura del proyecto

**AAMO** es un solo proyecto Django. El **motor** (`core/`) y los **usuarios** (`usuarios/`)
son globales; cada **área** es un paquete de primer nivel servido en su subdominio.

```
AAMO/
│
├── core/                   # MOTOR de la plataforma
│   ├── settings.py         #   configuración (BASE_DOMAIN, SSO, caché, storage…)
│   ├── middleware.py        #   EnrutadoPorAreaMiddleware (subdominio → urlconf + area)
│   ├── areas.py             #   registro AREAS + helpers de URL entre subdominios
│   ├── urls.py              #   APEX: login, selector de área, /panel/, /admin/, PWA
│   ├── urls_programacion.py #   urlconf del subdominio del área programación
│   ├── urls_financiera.py   #   urlconf del subdominio del área financiera
│   └── views.py             #   seleccion_area, panel_admin, vista_general, búsqueda
│
├── usuarios/               # GLOBAL: login único, perfiles, middleware de acceso, rate-limit
│
├── programacion/           # ÁREA programación (programacion.miltonochoa.app)
│   ├── urls.py              #   router del área (agrupa las 9 sub-apps en la raíz /)
│   ├── configuracion/       #   Catálogos: Materia, NombreLibro, Unidad, Colegio, ColegioAnio, Profesor
│   ├── colegios/            #   Grado, Bloque, Asignacion, Clase, ClaseParticular, HistorialCambio
│   ├── profesores/          #   Horario del profesor + portal con menú propio (Cronograma/Informes)
│   ├── auditoria/           #   Motor de detección + AlertaAuditoria + cron command
│   ├── informes/            #   Informes pedagógicos por sesión
│   ├── exportar/            #   Generación de Excel de horarios
│   ├── pagos/               #   Pagos semanales: LotePagos, PagoRealizado, ExtraPago, SoportePagoProfesor
│   ├── pendientes/          #   Tablero Kanban (home del área)
│   └── viaticos/            #   Solicitudes de viáticos: SolicitudViatico, GastoViatico, SoportePago
│
├── financiera/             # ÁREA financiera (financiera.miltonochoa.app)
│   ├── urls.py              #   router del área (raíz /): viaticos + pagos
│   ├── viaticos/            #   Inicio + gestión: devolver/aprobar/pagar/editar + soportes + Excel
│   └── pagos/               #   Pagos a profesores: semanas enviadas → marcar + soportes + Excel
│                            #   (sin modelos propios — importa de programacion.pagos)
│
├── logistica/              # PLACEHOLDER de área futura (solo __init__.py + README)
│
├── templates/              # Globales: base_chrome.html (chrome compartido), base.html
│                           #   (menú programación), base_financiera.html (menú financiera),
│                           #   base_apex.html (apex), home, 404, 500, login, sw.js
│
├── manage.py               # Entry point Django (apunta a core.settings)
├── requirements.txt        # Dependencias de producción
├── requirements-dev.txt    # Adicionales de desarrollo y testing
├── railway.json            # Build/deploy en Railway (Nixpacks: migrate → collectstatic → gunicorn)
├── .env / .env.dev-api     # Variables locales (gitignored; .env.dev-api → SQLite local)
├── README.md               # Este archivo
└── CLAUDE.md               # Guía interna para sesiones de Claude Code
```

> **Convención crítica — ruta de import ≠ `app_label`.** Las sub-apps viven dentro de
> `programacion/` pero conservan su label original (`configuracion`, `colegios`, …) definido
> en cada `apps.py` (`name='programacion.colegios'`, `label='colegios'`). Las tablas,
> migraciones y FKs por string (`'configuracion.Colegio'`) usan el **label** sin el prefijo
> `programacion.`. Imports Python: siempre `from programacion.<app>...`.

---

## Roles y control de acceso

**Login único + selección de área por subdominio.** Todos entran por el **apex**
(`miltonochoa.app/usuarios/login/`). Tras autenticarse, `core.views.seleccion_area`
resuelve las áreas del usuario y redirige al **subdominio** del área. La sesión se
comparte en `.miltonochoa.app` (**SSO**).

**Panel del superusuario.** El superusuario no entra al área directamente, sino al **panel**
(`miltonochoa.app/panel/`): acceso a todas las áreas y gestión de los **usuarios de etiqueta**
(alta/reset/baja). Los usuarios de colegio/profesor se gestionan dentro del área.

| Rol | Vinculación | Rutas permitidas (en `programacion.miltonochoa.app`) |
|-----|-------------|------------------------------------------------------|
| **Superusuario** | `User.is_superuser=True` | Todo |
| **Staff de área** | Grupo `area:programacion` | Todo el área (como superusuario), incluida gestión de usuarios de colegio/profesor; **salvo** el panel del apex, usuarios de etiqueta, `/admin/` y otras áreas |
| **Gestor colegio** | `UsuarioColegio` (OneToOne) | `/colegios/`, `/informes/` |
| **Profesor** | `UsuarioProfesor` (OneToOne) | `/profesores/`, `/informes/` — con menú propio (Cronograma · Informes · Pagos*) |

> El **staff de área financiera** (grupo `area:financiera`) accede a `financiera.miltonochoa.app`.

**Contraseñas (dos flujos):**
- **Colegios/profesores:** el staff asigna la contraseña a mano al crear y al resetear.
- **Empleados de área:** el admin crea el usuario con clave genérica + correo obligatorio. En el
  primer ingreso el sistema fuerza el cambio de contraseña. Hay auto-servicio
  "Olvidé mi contraseña" vía Resend/SMTP.

**Ratelimit** (`@rate_limit` en `usuarios/ratelimit.py`):
- Login: **10 intentos / 60 s** por IP.
- AJAX de unidades/materias: **200 / 60 s**.

---

## Instalación local

### Requisitos previos

- **Python 3.13** (compatible con 3.11+)
- **Git**

### 1 · Clonar e instalar dependencias

```bash
git clone <url-del-repo>
cd AAMO

# Crear y activar entorno virtual
python -m venv venv

# Windows (PowerShell)
.\venv\Scripts\Activate.ps1
# Linux / macOS
source venv/bin/activate

# Instalar dependencias (producción + desarrollo)
pip install -r requirements.txt -r requirements-dev.txt
```

### 2 · Configurar variables de entorno

Para **desarrollo local con SQLite** (sin tocar la BD de producción), crea `.env.dev-api` en
la raíz — se carga **antes** que `.env`. Hay una plantilla en [`.env.example`](.env.example):

```dotenv
DEBUG=True
DATABASE_URL=sqlite:///db.sqlite3
SECRET_KEY=<genera-una-con-get_random_secret_key>
BASE_DOMAIN=lvh.me
ALLOWED_HOSTS=localhost,127.0.0.1
SECURE_SSL_REDIRECT=False
CACHE_BACKEND=locmem
```

Para generar una `SECRET_KEY`:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### 3 · Migrar y crear superusuario

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 4 · Levantar el servidor

```bash
python manage.py runserver
```

**Enrutado por subdominios.** En dev usamos `lvh.me` (y `*.lvh.me`), que resuelven a
`127.0.0.1` sin tocar el archivo `hosts`:

| Host (dev) | Sirve |
|------------|-------|
| `http://lvh.me:8000/` | **Apex**: login único + selector de área + panel del superusuario |
| `http://programacion.lvh.me:8000/` | **Área Programación** |
| `http://financiera.lvh.me:8000/` | **Área Financiera** |

Abre `http://lvh.me:8000` → login en `/usuarios/login/` → tras entrar, el sistema
redirige al subdominio del área del usuario (o al `/panel/` si es superusuario).

---

## Variables de entorno

| Variable | Obligatoria | Default | Descripción |
|----------|:-----------:|---------|-------------|
| `SECRET_KEY` | Sí | — | Clave secreta de Django. Sin ella la app no arranca. |
| `DEBUG` | No | `False` | `True` para desarrollo local. |
| `ALLOWED_HOSTS` | No | `localhost,127.0.0.1` | Hosts extra (CSV). El apex y `.BASE_DOMAIN` se añaden solos. |
| `BASE_DOMAIN` | No | `miltonochoa.app` | Dominio base del enrutado por subdominios (dev: `lvh.me`). |
| `DATABASE_URL` | Sí | — | URL de PostgreSQL. En prod: **transaction pooler** de Supabase (`...pooler.supabase.com:6543`, usuario `postgres.<ref>`). En local: `sqlite:///db.sqlite3`. |
| `CONN_MAX_AGE` | No | `600` | Vida de conexiones persistentes (s). Con transaction pooler se usa `600` (conexiones calientes). |
| `DISABLE_SERVER_SIDE_CURSORS` | No | `False` | `True` con el transaction pooler de Supabase (pgbouncer en modo transaction). |
| `SECURE_SSL_REDIRECT` | No | `False` | `True` en producción si el dominio sirve HTTPS. |
| `CACHE_BACKEND` | No | `locmem` | `locmem` o `redis`. |
| `REDIS_URL` | Cond. | `redis://127.0.0.1:6379/1` | Solo si `CACHE_BACKEND=redis`. |
| `USE_SUPABASE_STORAGE` | No | `False` | `True` en prod → soportes de pago en Supabase Storage (S3). |
| `SUPABASE_BUCKET` | Cond. | — | Bucket privado (ej. `soportes-pago`). Obligatoria si `USE_SUPABASE_STORAGE=True`. |
| `SUPABASE_S3_ENDPOINT` | Cond. | — | Endpoint S3 de Supabase. Obligatoria si storage en Supabase. |
| `SUPABASE_S3_REGION` | Cond. | — | Región del bucket. Obligatoria si storage en Supabase. |
| `SUPABASE_S3_ACCESS_KEY` | Cond. | — | Access key S3. Obligatoria si storage en Supabase. |
| `SUPABASE_S3_SECRET_KEY` | Cond. | — | Secret key S3. Obligatoria si storage en Supabase. |
| `EMAIL_HOST_PASSWORD` | No | — | API key de Resend (re_…) para envío de correo en producción. |
| `VIATICOS_NOTIFICAR_A` | No | `marlon.medina@aamocolombia.com` | Destinatario de los avisos de viáticos. |
| `VIATICOS_LEGALIZACION_NOTIFICAR_A` | No | `financiero@aamocolombia.com` | Destinatario del aviso de legalización de viáticos enviada. |
| `BACKUP_DIR` | No | `backups/` | Directorio para respaldos. |

> Si existe `.env.dev-api` se carga **antes** del `.env`. Sirve para usar SQLite local sin
> tocar la configuración de producción.

---

## Tests y calidad

```bash
# Ejecutar toda la suite (usa SQLite, BASE_DOMAIN=testserver forzado)
python manage.py test

# Tests de una app específica
python manage.py test colegios
python manage.py test usuarios
python manage.py test financiera.viaticos

# Cobertura (requiere coverage)
coverage run --source='.' manage.py test
coverage report -m
coverage html  # → htmlcov/index.html
```

**Baseline actual: 400 tests OK.**

**Convenciones:**
- Tests con `unittest` / `Django TestCase`.
- BD de tests siempre SQLite y `BASE_DOMAIN=testserver` — forzados en `core/settings.py`.
- Los tests **de área** usan `Client(HTTP_HOST='programacion.testserver')`; los del **apex**
  (login, PWA) el host por defecto `testserver`.
- Los tests que suben archivos fuerzan disco local (`override_settings(STORAGES=...)` + tmp dir)
  → nunca tocan Supabase.

**Herramientas dev** (`requirements-dev.txt`):

- `django-debug-toolbar` 4.4.6 — panel de SQL/templates/signals
- `django-extensions` 4.1 — `shell_plus`, `runserver_plus`, `graph_models`
- `django-silk` 5.4.0 — profiling de queries y request timing
- `factory-boy` 3.3.1 — fixtures declarativos
- `coverage` 7.6.10 — cobertura de tests
- `pytest` / `pytest-django` 8.3.4 / 4.9.0 — disponible para migración futura

---

## Despliegue en producción

Despliegue continuo: **push a `main` en GitHub → deploy automático en Railway**.
Base de datos en **Supabase** (PostgreSQL). Dominio: `miltonochoa.app`.

### 1 · Base de datos (Supabase)

1. Crea un proyecto en Supabase.
2. Usa la cadena del **transaction pooler** (Supavisor, puerto `6543`, host
   `...pooler.supabase.com`, usuario `postgres.<project_ref>`) como `DATABASE_URL`.
   Es **obligatorio** con varios workers de gunicorn: multiplexa los backends y evita el
   agotamiento de conexiones. (NO uses `db.<ref>.supabase.co`: Supabase lo enruta a *session
   mode* y la app crashea al arrancar con `EMAXCONNSESSION`.) Sube el **Pool Size** del pooler
   a `30` (Database → Connection Pooling). Settings fuerza SSL en prod (`ssl_require=not DEBUG`).
3. Acompaña con `CONN_MAX_AGE=600` y `DISABLE_SERVER_SIDE_CURSORS=True`.

### 2 · App (Railway)

1. **New Project → Deploy from GitHub repo**. Railway construye con **Nixpacks** y respeta
   [`railway.json`](railway.json): en cada deploy ejecuta
   `migrate` → `collectstatic` → `gunicorn` (**6 workers, 4 hilos `gthread`**,
   `--worker-tmp-dir /dev/shm`, `--max-requests 800`, timeout 90 s).
2. **Auto-deploy:** branch de despliegue → `main`.
3. **Región:** co-localiza el servicio con Supabase (misma región, p. ej. **US West** si la
   BD está en `us-west-2`) con `railway service scale us-west=1 us-east=0`. Cross-región añade
   ~70 ms por query y degrada toda la concurrencia.
4. **Variables** mínimas:

   | Variable | Valor |
   |----------|-------|
   | `SECRET_KEY` | (genérala) |
   | `DEBUG` | `False` |
   | `BASE_DOMAIN` | `miltonochoa.app` |
   | `DATABASE_URL` | transaction pooler de Supabase (`:6543`, `postgres.<ref>`) |
   | `CONN_MAX_AGE` | `600` |
   | `DISABLE_SERVER_SIDE_CURSORS` | `True` |
   | `SECURE_SSL_REDIRECT` | `True` |

### 3 · Dominio y subdominios (DNS + TLS)

Añade el apex y cada área en *Settings → Networking → Custom Domain* de Railway:

| Dominio | Apunta a |
|---------|----------|
| `miltonochoa.app` (apex) | destino de Railway |
| `programacion.miltonochoa.app` | destino de Railway |
| `financiera.miltonochoa.app` | destino de Railway |

Railway emite el certificado TLS por dominio automáticamente. Todos los hosts llegan a la
**misma** app; `EnrutadoPorAreaMiddleware` decide el área por el subdominio.

**Auditoría programada (recomendado):** el dashboard ya **no** dispara la reconciliación de
alertas en cada carga (era un barrido global costoso bajo concurrencia). Programa un *Cron
Service* en Railway con `python manage.py ejecutar_auditoria` (sugerido cada 30 min) para
mantener las alertas frescas; la vista de Auditoría también las reconcilia al visitarla.

> Filesystem efímero en Railway — todos los Excel/ZIP se generan en `BytesIO` y se
> devuelven directamente en la respuesta HTTP (sin tocar disco).

---

## Añadir una nueva área

AAMO está diseñado para crecer por áreas. Para activar `logistica` (o cualquier otra):

1. **Crea las sub-apps** dentro del paquete del área (`logistica/`), igual que en
   `programacion/` (cada `apps.py` con `name='logistica.<app>'` y su `label`).
2. **Crea su `urlconf`** (p. ej. `core/urls_logistica.py`) que monte sus rutas en la raíz `/`.
3. **Regístrala** en [`core/areas.py`](core/areas.py) añadiendo una entrada a `AREAS`
   (`slug`, `nombre`, `urlconf`, `landing`) y, en `areas_del_usuario`, su condición de acceso.
4. **Crea el grupo de permisos** `area:logistica` (la "etiqueta" de staff del área).
5. **Añade su subdominio** `logistica.miltonochoa.app` en Railway (DNS + TLS).

El middleware de enrutado y el SSO funcionan sin más cambios.

---

## Mantenimiento

### Comandos útiles

```bash
# Crear migraciones tras cambios en modelos
python manage.py makemigrations
python manage.py migrate

# Verificación rápida (debe quedar limpio)
python manage.py check
python manage.py makemigrations --check --dry-run

# Auditoría manual
python manage.py ejecutar_auditoria

# Recolectar estáticos antes de desplegar
python manage.py collectstatic --noinput

# Shell con autoload de modelos (django-extensions)
python manage.py shell_plus
```

### Logs

- Rotating file handler: `logs/app.log` (5 MB × 5 backups).
- Logger principal: `aamo` (DEBUG en dev, INFO en prod).

### Caché

Si trabajas en `vista_general` o `auditoria/engine.py`, los signals de `colegios/signals.py`
invalidan la caché al modificar `Clase` / `Asignacion` automáticamente.

### Grafo de conocimiento (graphify)

El repo incluye soporte para el skill `/graphify` de Claude Code, que genera un mapa de
dependencias y comunidades del código en `graphify-out/`. Si modificas la estructura del
proyecto, regenera el grafo con `/graphify . --update` para mantenerlo actualizado. El directorio
`graphify-out/` está en `.gitignore` (artefacto regenerable, no se versiona).

---

## Contribuir

1. Sincroniza `dev` (`git checkout dev && git pull --ff-only origin dev`) y crea una rama
   desde ahí: `git checkout -b feat/mi-feature`. **Nunca** se commitea directo a `dev` ni a `main`.
2. Comenta el **porqué** de decisiones no obvias, no el **qué**.
3. Respeta la convención **ruta de import ≠ `app_label`** (ver [Estructura](#️-estructura-del-proyecto)).
4. Añade/actualiza tests y ejecuta `python manage.py test` (baseline: 400 tests OK).
5. Si tocas modelos, **incluye la migración** en el commit.
6. Si modificas la estructura (rutas, modelos, áreas), actualiza también
   [`CLAUDE.md`](CLAUDE.md) y regenera el grafo con `/graphify . --update`.
7. Para actualizar este README, usa el skill `/readme` de Claude Code.
8. Abre un PR contra `dev` con descripción clara del cambio y su motivación.
   `dev` se promociona a `main` (deploy automático en Railway) por su propio PR.

---

## Licencia

Este proyecto es **de uso interno** de la organización **Milton Ochoa / AAMO**. No está
licenciado para distribución pública.

---

<div align="center">

**Hecho con dedicación por el equipo AAMO**

<sub>© 2026 AAMO · Plataforma multi-área</sub>

</div>
