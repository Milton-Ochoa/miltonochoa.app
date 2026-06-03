<div align="center">

<img src="https://img.shields.io/badge/AAMO-Plataforma-212529?style=for-the-badge&labelColor=0d6efd" alt="AAMO"/>

# 🏛️ AAMO

### Plataforma web multi-área para la organización educativa **Milton Ochoa / AAMO**

*Un solo proyecto Django, un solo login. Cada **área** del negocio vive en su propio **subdominio**, sobre una única base de datos.*

<br/>

[![Django](https://img.shields.io/badge/Django-5.2.11-092E20?style=flat&logo=django&logoColor=white)](https://www.djangoproject.com/)
[![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Supabase-336791?style=flat&logo=postgresql&logoColor=white)](https://supabase.com/)
[![DRF](https://img.shields.io/badge/DRF-3.15-A30000?style=flat&logo=django&logoColor=white)](https://www.django-rest-framework.org/)
[![HTMX](https://img.shields.io/badge/HTMX-1.9-3D72D7?style=flat&logo=htmx&logoColor=white)](https://htmx.org/)
[![Bootstrap](https://img.shields.io/badge/Bootstrap-5.3-7952B3?style=flat&logo=bootstrap&logoColor=white)](https://getbootstrap.com/)
[![PWA](https://img.shields.io/badge/PWA-ready-5A0FC8?style=flat&logo=pwa&logoColor=white)](https://web.dev/progressive-web-apps/)
[![Railway](https://img.shields.io/badge/Deploy-Railway-0B0D0E?style=flat&logo=railway&logoColor=white)](https://railway.app/)
[![License](https://img.shields.io/badge/Uso-Interno-lightgrey?style=flat)](#-licencia)

</div>

---

## 📖 Tabla de contenidos

- [✨ Visión general](#-visión-general)
- [🧭 Áreas de la plataforma](#-áreas-de-la-plataforma)
- [🏗️ Arquitectura multi-área](#️-arquitectura-multi-área)
- [📚 Área Programación](#-área-programación)
- [🛠️ Stack tecnológico](#️-stack-tecnológico)
- [🗂️ Estructura del proyecto](#️-estructura-del-proyecto)
- [🔐 Roles y control de acceso](#-roles-y-control-de-acceso)
- [📦 Instalación local](#-instalación-local)
- [⚙️ Variables de entorno](#️-variables-de-entorno)
- [📡 API REST](#-api-rest)
- [🧪 Tests y calidad](#-tests-y-calidad)
- [☁️ Despliegue en producción](#️-despliegue-en-producción)
- [➕ Añadir una nueva área](#-añadir-una-nueva-área)
- [🩹 Mantenimiento](#-mantenimiento)
- [🤝 Contribuir](#-contribuir)
- [📜 Licencia](#-licencia)

---

## ✨ Visión general

**AAMO** es la plataforma web interna de la organización educativa **Milton Ochoa / AAMO**.
Está construida como **un único proyecto Django** organizado por **áreas** de negocio
(programación académica, logística, financiera…), donde:

- 🏛️ **Un solo edificio, varias áreas.** Todo vive en el mismo proyecto y comparte
  una **única base de datos** y un **único sistema de usuarios**.
- 🌐 **Cada área es un subdominio.** El **apex** (`miltonochoa.app`) es el login único
  y el selector de área; cada área se sirve en su propio host
  (`programacion.miltonochoa.app`, y en el futuro `logistica.`, `financiera.`).
- 🔑 **Un solo login (SSO).** El usuario se autentica una vez en el apex y, según sus
  permisos, es redirigido al subdominio de su área. La sesión se comparte entre todos
  los subdominios.
- 🧩 **Crece por áreas.** Añadir un área nueva es registrar su `urlconf` y su subdominio;
  el motor de enrutado del `core/` hace el resto (ver [Añadir una nueva área](#-añadir-una-nueva-área)).

> **Idioma:** Español (Colombia) · **Zona horaria:** America/Bogota · **Moneda:** COP
> **Dominio:** `miltonochoa.app` (dev: `lvh.me`)

---

## 🧭 Áreas de la plataforma

| Área | Subdominio | Estado | Qué hace |
|------|------------|:------:|----------|
| 🏛️ **Apex** | `miltonochoa.app` | ✅ Activa | Login único, selector de área y **panel del superusuario** (`/panel/`). |
| 📚 **Programación** | `programacion.miltonochoa.app` | ✅ Activa | Gestión académica integral: calendario, auditoría, informes, pagos, viáticos y API REST. |
| 💰 **Financiera** | `financiera.miltonochoa.app` | ✅ Activa | Inicio + gestión de solicitudes de viáticos (devolver / aprobar / pagar / editar, con badge de pendientes). Acceso por grupo `area:financiera`. |
| 🚚 **Logística** | `logistica.miltonochoa.app` | 🚧 Placeholder | Reservada. Paquete creado, sin apps ni rutas todavía. |

**Programación** y **Financiera** comparten el mismo *chrome* (sidebar, header, footer,
estilos) definido en `templates/base_chrome.html`; cada área solo aporta su menú y títulos
(`templates/base.html`, `templates/base_financiera.html`). `logistica/` sigue siendo un
paquete Python vacío listo para crecer con el mismo patrón.

---

## 🏗️ Arquitectura multi-área

El corazón de AAMO es el **enrutado por subdominio**: el mismo proyecto Django responde en
todos los hosts, y un middleware elige qué `urlconf` montar según el subdominio de la petición.

```
                         🌐 Cliente (navegador / PWA)
                                     │  HTTP(S)
        ┌────────────────────────────┼────────────────────────────┐
        │                            │                            │
        ▼                            ▼                            ▼
 miltonochoa.app          programacion.miltonochoa.app    logistica.· financiera.·
   (APEX)                      (ÁREA programacion)            (futuras áreas)
        │                            │                            │
        └────────────────────────────┴────────────────────────────┘
                                     │
            ┌────────────────────────▼─────────────────────────┐
            │  🛡️  core.middleware.EnrutadoPorAreaMiddleware    │
            │  Mira el host → fija request.urlconf y request.area│
            │   · apex            → core.urls                    │
            │   · <area>.dominio  → urlconf del área (core.areas)│
            │   · subdominio sin área registrada → 404           │
            └────────────────────────┬─────────────────────────┘
                                     │
            ┌────────────────────────▼─────────────────────────┐
            │  👥 usuarios.middleware.ControlAcceso              │
            │  Solo dentro de un área: login + scope por rol     │
            │  + inyecta el perfil en request                    │
            └────────────────────────┬─────────────────────────┘
                                     │
   ┌──────────────────┬──────────────┼───────────────────┬──────────────────┐
   ▼                  ▼              ▼                   ▼                  ▼
📄 Vistas HTMX   🔌 API REST   ⚙️ Comandos manage   🔑 Login/SSO      📲 PWA (manifest+sw)
   │                  │              │                   │                  │
   └──────────────────┴──────────────┴───────────────────┴──────────────────┘
                                     │
            ┌────────────────────────▼─────────────────────────┐
            │   💾 ORM Django · Signals · Caché (locmem/Redis)   │
            └────────────────────────┬─────────────────────────┘
                                     │
   🐘 PostgreSQL (Supabase, producción)        🗃️ SQLite (local / tests)
```

**Piezas clave (todas en `core/`):**

| Pieza | Rol |
|-------|-----|
| [`core/middleware.py`](core/middleware.py) | `EnrutadoPorAreaMiddleware`: elige `urlconf` y fija `request.area` según el host. Host ajeno (localhost/IP/healthcheck) → apex. |
| [`core/areas.py`](core/areas.py) | Registro único `AREAS` (slug → urlconf + landing) y helpers de URL **entre hosts** (`url_en_area`, `url_apex`, `areas_del_usuario`). |
| [`core/urls.py`](core/urls.py) | **Apex**: `/` → selector de área, `/panel/` → panel del superusuario, `/usuarios/` → login, `/admin/`, PWA. **No** monta áreas. |
| [`core/urls_programacion.py`](core/urls_programacion.py) | **Área programación**: monta `programacion.urls` en la raíz `/` de su subdominio + login local + PWA. |

> **SSO entre subdominios:** la sesión y el CSRF se comparten vía
> `SESSION_COOKIE_DOMAIN=.BASE_DOMAIN`. Un único login vale para todos los subdominios.

> **Patrón híbrido HTMX + DRF:** las pantallas internas son HTML server-rendered con HTMX
> para interactividad parcial; la API DRF expone los datos a sistemas externos con JWT.

---

## 📚 Área Programación

El área **Programación** (`programacion.miltonochoa.app`) gestiona la programación académica
de extremo a extremo. Es un paquete Python (`programacion/`) que agrupa **8 sub-apps**.

### 🗓️ Programación visual

- **Vista general**: calendario unificado de todos los colegios activos, agrupado por
  colegio → grado → bloque, con caché HTML por mes (10 min).
- **Dashboard por colegio**: matriz `grado × fecha` editable inline con HTMX, con recálculo
  automático de secuencia al mover clases.
- **Recomendación inteligente** de la siguiente unidad al programar, considerando libro
  asignado, fecha y socializaciones.
- **Clases particulares** fuera del horario regular.

### 🗂️ Catálogo modular

- **Colegio ↔ Colegio-Año**: separa datos invariantes (nombre, ciudad…) de los anuales
  (tarifa por hora, activo/inactivo) → historial sin duplicar registros.
- **Libros normales vs. material asignado**: dos categorías con flujos distintos.
- **Asignaciones por rango de fechas**: un grado puede cambiar de libro a mitad de año sin
  perder consistencia.

### 🚨 Auditoría automática

| Tipo de alerta | Detecta |
|----------------|---------|
| 🔁 **Duplicado** | Misma unidad de la misma materia programada >1 vez en `(colegio, grado, libro)` |
| ⚔️ **Conflicto** | Un profesor con clases en >1 colegio el mismo día |
| 📉 **Secuencia** | Salto en la numeración de unidades (ej. pasó de 2 a 4) |

- Deduplicación por **hash MD5** → no se crean alertas repetidas.
- Reactivación automática si un error reaparece (salvo que se haya ignorado manualmente).
- Throttle de 5 minutos para evitar barridos concurrentes a la BD.
- Comando de cron: `python manage.py ejecutar_auditoria`.

### 📝 Informes pedagógicos

- Un `Informe` está vinculado a **exactamente una** clase regular o particular (garantizado
  por `CheckConstraint` a nivel BD).
- Datos de cabecera **desnormalizados** para sobrevivir aunque se elimine la clase original.
- Estados: borrador → completado (al rellenar `actividades`).

### 💵 Liquidación de pagos

- Cálculo `horas × ColegioAnio.valor_hora` por profesor / colegio / fecha.
- Registro `PagoRealizado` **inmutable** con valor desnormalizado (preserva tarifa histórica).
- Constraint `unique_together (profesor, colegio, fecha)` impide doble liquidación.

### 📊 Exportación Excel

- Generación 100 % en memoria con **openpyxl** (sin tocar disco — ideal para el filesystem
  efímero de Railway).
- ZIPs masivos (un Excel por profesor o por colegio).
- Filtro `_safe_url()` contra hipervínculos maliciosos en celdas.
- Días/meses **siempre en español**, independiente del locale del SO.

### 📋 Tablero Kanban (home del área)

Pendientes con tres columnas (Pendiente · En gestión · Completado), operable con HTMX y
arrastrable entre estados.

### 🔌 API REST + 📲 PWA

- **API REST** documentada (Swagger/ReDoc) con JWT — ver [API REST](#-api-rest).
- **PWA** instalable: `manifest.json` y `sw.js` servidos desde la raíz del subdominio (scope
  `/` por origen → cada área es una PWA independiente), con theme color y safe-area-inset.

---

## 🛠️ Stack tecnológico

<table>
<tr><th>Capa</th><th>Tecnología</th><th>Versión</th></tr>
<tr><td>🐍 Backend</td><td>Django</td><td>5.2.11</td></tr>
<tr><td>🐍 Runtime</td><td>Python (pin en <code>.python-version</code>)</td><td>3.13</td></tr>
<tr><td>⚡ Interactividad</td><td>HTMX + django-htmx</td><td>1.9.12 / 1.19.0</td></tr>
<tr><td>🎨 UI</td><td>Bootstrap + Font Awesome</td><td>5.3 / 6.0</td></tr>
<tr><td>🗄️ BD producción</td><td>PostgreSQL (Supabase pooler)</td><td>—</td></tr>
<tr><td>🧪 BD tests</td><td>SQLite</td><td>auto</td></tr>
<tr><td>🔌 API</td><td>Django REST Framework</td><td>3.15.2</td></tr>
<tr><td>🔑 Auth API</td><td>djangorestframework-simplejwt</td><td>5.3.1</td></tr>
<tr><td>📚 Docs API</td><td>drf-spectacular (OpenAPI 3)</td><td>0.27.2</td></tr>
<tr><td>🔍 Filtros API</td><td>django-filter</td><td>24.3</td></tr>
<tr><td>⚡ Caché</td><td>locmem (default) · django-redis (opt)</td><td>5.4.0</td></tr>
<tr><td>📦 Estáticos</td><td>WhiteNoise (gzip + manifest)</td><td>6.12.0</td></tr>
<tr><td>📊 Excel</td><td>openpyxl</td><td>3.1.5</td></tr>
<tr><td>🚀 WSGI prod</td><td>gunicorn</td><td>25.3.0</td></tr>
<tr><td>🌐 PaaS</td><td>Railway (deploy desde <code>main</code>)</td><td>—</td></tr>
<tr><td>🐘 BD gestionada</td><td>Supabase (PostgreSQL)</td><td>—</td></tr>
</table>

---

## 🗂️ Estructura del proyecto

**AAMO** es un solo proyecto Django. El **motor** (`core/`) y los **usuarios** (`usuarios/`)
son globales; cada **área** es un paquete de primer nivel servido en su subdominio.

```
AAMO/
│
├── 🧩 core/                  # MOTOR de la plataforma
│   ├── settings.py           #   configuración (BASE_DOMAIN, SSO, caché, DRF, JWT…)
│   ├── middleware.py         #   EnrutadoPorAreaMiddleware (subdominio → urlconf + area)
│   ├── areas.py              #   registro AREAS + helpers de URL entre subdominios
│   ├── urls.py               #   APEX: login, selector de área, /panel/, /admin/, PWA
│   ├── urls_programacion.py  #   urlconf del subdominio del área programación
│   └── views.py              #   seleccion_area, panel_admin, vista_general, búsqueda
│
├── 👥 usuarios/              # GLOBAL: login único, perfiles, middleware de acceso, rate-limit
│
├── 📚 programacion/          # ÁREA programación (servida en programacion.miltonochoa.app)
│   ├── urls.py               #   router del área (agrupa las sub-apps en la raíz /)
│   ├── 🗂️  configuracion/     #   Catálogos: Materia, Libro, Unidad, Colegio, ColegioAnio, Profesor
│   ├── 🏫 colegios/          #   Grado, Bloque, Asignacion, Clase, ClaseParticular, HistorialCambio
│   ├── 👨‍🏫 profesores/         #   Vista de horario propio del profesor
│   ├── 🚨 auditoria/         #   Motor de detección de errores + AlertaAuditoria + cron command
│   ├── 📝 informes/          #   Informes pedagógicos por sesión
│   ├── 📊 exportar/          #   Generación de Excel + modelo PagoRealizado
│   ├── 📋 pendientes/        #   Tablero Kanban (home del área)
│   ├── ✈️  viaticos/          #   Solicitudes de viáticos (SolicitudViatico, GastoViatico)
│   └── 🔌 api/               #   DRF: serializers, viewsets, urls, paginación, tests
│
├── 💰 financiera/            # ÁREA financiera (servida en financiera.miltonochoa.app)
│   ├── urls.py               #   router del área (raíz /)
│   └── 💵 viaticos/          #   Inicio + gestión de viáticos: devolver/aprobar/pagar/editar
│                             #   (sin modelos: importa los de programacion.viaticos)
├── 🚚 logistica/             # PLACEHOLDER de área futura (solo __init__.py + README)
│
├── 🎨 templates/             # Globales: base_chrome.html (chrome compartido), base.html
│                             #   (menú programación), base_financiera.html (menú financiera),
│                             #   base_apex.html (apex/lobby), home, 404, 500, login, sw.js
├── 📜 logs/                  # Rotating file handler (5MB × 5 backups, gitignored)
├── 💾 backups/               # AAMO_export.xlsx (respaldo de BD)
│
├── 🚀 manage.py              # Entry point Django (apunta a core.settings)
├── 📦 requirements.txt       # Dependencias de producción
├── 🛠️  requirements-dev.txt  # Adicionales de desarrollo y testing
├── 🔒 .env / .env.dev-api    # Variables locales (gitignored; .env.dev-api → SQLite local)
├── 🚂 railway.json           # Build/deploy en Railway (Nixpacks: migrate → collectstatic → gunicorn)
├── 📄 README.md              # Este archivo
└── 🤖 CLAUDE.md              # Guía interna para sesiones de Claude Code
```

> **Convención crítica — ruta de import ≠ `app_label`.** Las sub-apps viven dentro de
> `programacion/` pero conservan su label original (`configuracion`, `colegios`, …) definido
> en cada `apps.py` (`name='programacion.colegios'`, `label='colegios'`). Por eso las tablas,
> migraciones y FKs por string (`'configuracion.Colegio'`) **no cambiaron** al unificar el
> proyecto. Imports Python: siempre `from programacion.<app>...`; FKs por string e
> `include()` usan el label sin el prefijo.

---

## 🔐 Roles y control de acceso

**Login único + selección de área por subdominio.** Todos entran por el **apex**
(`miltonochoa.app/usuarios/login/`). Tras autenticarse, `core.views.seleccion_area` /
`usuarios.views.login_redirect` resuelven las áreas del usuario (vía el grupo
`area:programacion` o un perfil de colegio/profesor; el superusuario tiene todas) y redirigen
al **subdominio** del área. Si tiene varias, muestra un selector; si no tiene ninguna, un
mensaje claro. Entrar directo a un subdominio sin sesión envía al login del apex. La sesión se
comparte en `.miltonochoa.app` (**SSO**).

**Panel del superusuario.** El superusuario no entra al área directamente, sino al **panel**
(`miltonochoa.app/panel/`, `core.views.panel_admin`): acceso a todas las áreas y gestión de
los **usuarios de etiqueta** (alta/reset/baja). Los usuarios de colegio/profesor se gestionan
dentro del área (`/usuarios/colegios/`, `/usuarios/profesores/`), enlazados desde el panel.

El middleware de host [`core/middleware.py`](core/middleware.py) elige el `urlconf` según el
subdominio; el de acceso [`usuarios/middleware.py`](usuarios/middleware.py) impone scope por
rol **dentro del subdominio del área** (en el apex deja pasar — sus vistas usan decoradores):

| Rol | Vinculación | Rutas permitidas (en `programacion.miltonochoa.app`) | Atributos en `request` |
|-----|-------------|------------------------------------------------------|------------------------|
| 👑 **Superusuario** | `User.is_superuser=True` | Todo | `perfil_colegio=None`, `perfil_profesor=None`, `es_personal_programacion=True` |
| 🛠️ **Staff de área** | Grupo `area:programacion` | Todo el área (como superusuario), incluida la gestión de usuarios de colegio/profesor; **salvo** el panel del apex, los usuarios de etiqueta, `/admin/` y otras áreas | `perfil_colegio=None`, `perfil_profesor=None`, `es_personal_programacion=True` |
| 🏫 **Gestor colegio** | `UsuarioColegio` (OneToOne) | `/colegios/`, `/informes/` | `perfil_colegio`, `colegio_anio_activo` |
| 👨‍🏫 **Profesor** | `UsuarioProfesor` (OneToOne) | `/profesores/`, `/informes/` | `perfil_profesor` |

> El **staff de área** es la "etiqueta" `area:programacion`: usuarios genéricos del área sin
> perfil de colegio/profesor, creados desde el panel. El predicado de acceso de página es
> `core.areas.es_personal_programacion` (superusuario **o** miembro del grupo); no son
> `is_staff` (no entran a `/admin/`).

> ⚠️ Un usuario autenticado **sin perfil/área vinculada** se desloguea automáticamente. El
> login (`/usuarios/`) y las rutas PWA (`/manifest.json`, `/sw.js`) quedan fuera del scope de
> área; la API REST usa JWT propio.

**Ratelimit** (decorador `@rate_limit(max_calls, periodo)` en `usuarios/ratelimit.py`):
- 🔐 Login: **10 intentos / 60 s** por IP.
- 📚 AJAX de unidades/materias: **200 / 60 s**.

---

## 📦 Instalación local

### Requisitos previos

- **Python 3.13** (versión fijada en `.python-version`; compatible con 3.11+)
- **PostgreSQL** (o usar la BD remota de Supabase con la URL del `.env`)
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
`127.0.0.1` sin tocar el archivo `hosts` — basta con `BASE_DOMAIN=lvh.me` en `.env.dev-api`:

| Host (dev) | Sirve |
|------------|-------|
| `http://lvh.me:8000/` | **Apex**: login único + selector de área + panel del superusuario |
| `http://programacion.lvh.me:8000/` | **Área Programación** (Kanban, colegios, API…) |

🌐 Abre [http://lvh.me:8000](http://lvh.me:8000) → login en `/usuarios/login/` → tras entrar,
el sistema redirige al **subdominio** del área del usuario (o al `/panel/` si es superusuario).
La sesión se comparte en `.lvh.me`, así un solo login vale para todos los subdominios (SSO).

---

## ⚙️ Variables de entorno

| Variable | Obligatoria | Default | Descripción |
|----------|:-----------:|---------|-------------|
| `SECRET_KEY` | ✅ | — | Clave secreta de Django. Sin ella la app no arranca. |
| `DEBUG` | ❌ | `False` | `True` para desarrollo local. |
| `ALLOWED_HOSTS` | ❌ | `localhost,127.0.0.1` | Hosts extra (CSV). El apex y `.BASE_DOMAIN` se añaden solos. |
| `BASE_DOMAIN` | ❌ | `miltonochoa.app` | Dominio base del enrutado por subdominios (dev: `lvh.me`; tests: `testserver`). |
| `DATABASE_URL` | ✅ | — | URL completa de PostgreSQL (Supabase) o `sqlite:///db.sqlite3` en local. |
| `SECURE_SSL_REDIRECT` | ❌ | `False` | `True` en producción si el dominio sirve HTTPS. |
| `CACHE_BACKEND` | ❌ | `locmem` | `locmem` o `redis`. |
| `REDIS_URL` | ⚠️ | `redis://127.0.0.1:6379/1` | Solo si `CACHE_BACKEND=redis`. |
| `BACKUP_DIR` | ❌ | `backups/` | Directorio para backups (`BASE_DIR/backups`). |

> 💡 Si existe `.env.dev-api` se carga **antes** del `.env`. Sirve para usar SQLite local sin
> tocar la config de producción.

---

## 📡 API REST

La API vive en el **subdominio del área**:
`https://programacion.miltonochoa.app/api/v1/` (dev: `http://programacion.lvh.me:8000/api/v1/`).
Se usa para integraciones externas (p. ej. el sistema financiero).

### 🔑 Autenticación (JWT)

```bash
# Obtener token
curl -X POST http://programacion.lvh.me:8000/api/v1/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "***"}'
# → { "access": "eyJ...", "refresh": "eyJ..." }

# Refrescar
curl -X POST http://programacion.lvh.me:8000/api/v1/auth/token/refresh/ \
  -H "Content-Type: application/json" \
  -d '{"refresh": "eyJ..."}'
```

| Token | Vigencia |
|-------|----------|
| Access | 8 horas |
| Refresh | 7 días |

### 📚 Documentación interactiva

| Recurso | URL |
|---------|-----|
| 🧪 Swagger UI | [`/api/v1/docs/`](http://programacion.lvh.me:8000/api/v1/docs/) |
| 📖 ReDoc | [`/api/v1/redoc/`](http://programacion.lvh.me:8000/api/v1/redoc/) |
| 📄 OpenAPI schema | [`/api/v1/schema/`](http://programacion.lvh.me:8000/api/v1/schema/) |

### 🛣️ Endpoints disponibles

| Recurso | Métodos | Descripción |
|---------|---------|-------------|
| `/api/v1/profesores/` | `GET` | Listado de profesores con filtros y búsqueda |
| `/api/v1/colegios/` | `GET` | Catálogo base de colegios |
| `/api/v1/colegios-anio/` | `GET` | Instancias anuales con `valor_hora` |
| `/api/v1/clases/` | `GET` | Clases programadas (filtros: desde/hasta, profesor, colegio) |
| `/api/v1/clases-particulares/` | `GET` | Clases particulares |
| `/api/v1/pagos/` | `GET`, `POST` | Pagos realizados — crear marca `marcado_por=request.user` |

**Paginación**: 200/página por defecto, `?page_size=N` (máx 1000).
**Throttle**: `1000/hora/usuario`.

---

## 🧪 Tests y calidad

```bash
# Ejecutar toda la suite (usa SQLite, BASE_DOMAIN=testserver forzado)
python manage.py test

# Tests de una app específica
python manage.py test api
python manage.py test colegios
python manage.py test usuarios

# Cobertura (requiere coverage)
coverage run --source='.' manage.py test
coverage report -m
coverage html  # → htmlcov/index.html
```

**Convenciones**:
- Tests con `unittest`/`Django TestCase` (pytest está disponible para migración futura).
- BD de tests siempre SQLite y `BASE_DOMAIN=testserver` — forzados en `core/settings.py`
  cuando `'test' in sys.argv`.
- Los tests **de área** usan `Client(HTTP_HOST='programacion.testserver')`; los del **apex**
  (login, PWA) el host por defecto `testserver`.

**Herramientas dev disponibles** (ver `requirements-dev.txt`):

- 🐛 `django-debug-toolbar` — panel de SQL/templates/signals
- 🔬 `django-extensions` — `shell_plus`, `runserver_plus`, `graph_models`
- 🧵 `django-silk` — profiling de queries y request timing
- 🏭 `factory-boy` — fixtures declarativos

---

## ☁️ Despliegue en producción

Despliegue continuo: **push a `main` en GitHub → deploy automático en Railway**. Base de datos
gestionada en **Supabase** (PostgreSQL). El dominio definitivo es `miltonochoa.app`, con cada
área en su subdominio.

### 1 · Base de datos (Supabase)

1. Crea un proyecto en Supabase.
2. Copia la cadena del **Session pooler** (puerto `5432`):
   `postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres`.
   (Settings ya fuerza SSL en producción vía `dj_database_url(ssl_require=not DEBUG)`.)

### 2 · App (Railway)

1. **New Project → Deploy from GitHub repo** y selecciona este repositorio. Railway construye
   con **Nixpacks** y respeta [`railway.json`](railway.json): en cada deploy ejecuta
   `migrate` → `collectstatic` → `gunicorn` (1 worker + 3 hilos `gthread`; ver nota de caché abajo).
2. **Auto-deploy:** en *Settings → Service*, deja el branch de despliegue en `main`.
3. **Variables** (*Variables*):

   | Variable | Valor |
   |----------|-------|
   | `SECRET_KEY` | (genérala) |
   | `DEBUG` | `False` |
   | `BASE_DOMAIN` | `miltonochoa.app` |
   | `ALLOWED_HOSTS` | `<tu-app>.up.railway.app` *(el apex y `.miltonochoa.app` se añaden solos)* |
   | `DATABASE_URL` | cadena del Session pooler de Supabase |
   | `SECURE_SSL_REDIRECT` | `True` |
   | `CACHE_BACKEND` | `redis` + `REDIS_URL` *(opcional)* |

### 3 · Dominio y subdominios (DNS + TLS)

En *Settings → Networking → Custom Domain* de Railway añade el apex y **cada área**, y crea los
registros DNS que Railway indique (normalmente `CNAME`):

| Dominio | Apunta a |
|---------|----------|
| `miltonochoa.app` (apex) | destino de Railway |
| `www.miltonochoa.app` | destino de Railway |
| `programacion.miltonochoa.app` | destino de Railway |
| *(futuro)* `logistica.` / `financiera.` | destino de Railway |

Railway emite el certificado TLS por dominio automáticamente. Todos los hosts llegan a la
**misma** app; `EnrutadoPorAreaMiddleware` decide el área por el subdominio.

**Auditoría programada:** crea en Railway un *Cron Service* con
`python manage.py ejecutar_auditoria` (sugerido cada 30 min).

> ⚠️ Filesystem efímero en Railway — todos los Excel/ZIP se generan en `BytesIO` y se
> devuelven directamente en la respuesta.

**Cabeceras de seguridad activadas con `DEBUG=False`:** `SECURE_SSL_REDIRECT` (configurable),
`SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SESSION_COOKIE_HTTPONLY`,
`SECURE_CONTENT_TYPE_NOSNIFF`, HSTS 1 año (`includeSubDomains` + `preload`) y `XFrameOptions`.

---

## ➕ Añadir una nueva área

AAMO está diseñado para crecer por áreas. Para activar `logistica` (o cualquier otra):

1. **Crea las sub-apps** dentro del paquete del área (`logistica/`), igual que en
   `programacion/` (cada `apps.py` con `name='logistica.<app>'` y su `label`).
2. **Crea su `urlconf`** (p. ej. `core/urls_logistica.py`) que monte sus rutas en la raíz `/`.
3. **Regístrala** en [`core/areas.py`](core/areas.py) añadiendo una entrada a `AREAS`
   (`slug`, `nombre`, `urlconf`, `landing`) y, en `areas_del_usuario`, su condición de acceso.
4. **Crea el grupo de permisos** `area:logistica` (la "etiqueta" de staff del área).
5. **Añade su subdominio** `logistica.miltonochoa.app` en Railway (DNS + TLS).

El middleware de enrutado y el SSO funcionan sin más cambios: el nuevo subdominio empieza a
servir su área automáticamente.

> Los `README.md` dentro de `logistica/` y `financiera/` documentan este mismo proceso a nivel
> de paquete.

---

## 🩹 Mantenimiento

### Comandos útiles

```bash
# Crear migraciones tras cambios en modelos
python manage.py makemigrations
python manage.py migrate

# Verificación rápida (debe quedar limpio)
python manage.py check
python manage.py makemigrations --check --dry-run

# Auditoría manual (ignora throttle de 5 min)
python manage.py ejecutar_auditoria

# Recolectar estáticos antes de desplegar
python manage.py collectstatic --noinput

# Shell con autoload de modelos (django-extensions)
python manage.py shell_plus
```

### Logs

- Rotating file handler: `logs/app.log` (5 MB × 5 backups).
- Logger principal: `aamo` (DEBUG en dev, INFO en prod). En `DEBUG=True` también va a consola.

### Caché

Si trabajas en `vista_general` o `auditoria/engine.py`, recuerda invalidar la caché (los
signals de `colegios/signals.py` lo hacen al modificar `Clase`/`Asignacion`).

---

## 🤝 Contribuir

1. Crea una rama desde `main`: `git checkout -b feat/mi-feature`.
2. Sigue las convenciones del repo: comenta el **porqué** de decisiones no obvias, no el **qué**.
3. Respeta la convención **ruta de import ≠ `app_label`** (ver [Estructura](#️-estructura-del-proyecto)).
4. Añade/actualiza tests en la app correspondiente y ejecuta `python manage.py test`.
5. Si tocas modelos, **incluye la migración** en el commit.
6. Abre un PR contra `main` con una descripción clara del cambio y su motivación.

> 📖 Si modificas algo estructural (rutas, modelos, signals, áreas), **actualiza también
> [`CLAUDE.md`](CLAUDE.md)** para mantener la guía interna sincronizada.

---

## 📜 Licencia

Este proyecto es **de uso interno** de la organización **Milton Ochoa / AAMO**. No está
licenciado para distribución pública.

---

<div align="center">

**Hecho con ❤️ por el equipo AAMO**

<sub>© 2026 AAMO · Plataforma multi-área</sub>

</div>
