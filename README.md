<div align="center">

<img src="https://img.shields.io/badge/AAMO-Programaci%C3%B3n-212529?style=for-the-badge&labelColor=0d6efd" alt="AAMO Programación"/>

# 📚 Programación AAMO

### Sistema integral de gestión académica para colegios — Milton Ochoa / AAMO

*Calendario, programación, auditoría automática, informes pedagógicos, liquidación de pagos y API REST en una sola plataforma.*

<br/>

[![Django](https://img.shields.io/badge/Django-5.2.11-092E20?style=flat&logo=django&logoColor=white)](https://www.djangoproject.com/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
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
- [🚀 Características principales](#-características-principales)
- [🛠️ Stack tecnológico](#️-stack-tecnológico)
- [🏗️ Arquitectura](#️-arquitectura)
- [📦 Instalación local](#-instalación-local)
- [⚙️ Variables de entorno](#️-variables-de-entorno)
- [🧭 Estructura del proyecto](#-estructura-del-proyecto)
- [🔐 Roles y control de acceso](#-roles-y-control-de-acceso)
- [📡 API REST](#-api-rest)
- [🧪 Tests y calidad](#-tests-y-calidad)
- [☁️ Despliegue en producción](#️-despliegue-en-producción)
- [🩹 Mantenimiento](#-mantenimiento)
- [🤝 Contribuir](#-contribuir)
- [📜 Licencia](#-licencia)

---

## ✨ Visión general

**Programación AAMO** es una aplicación web desarrollada en Django para que la organización educativa **Milton Ochoa / AAMO** gestione su programación académica de extremo a extremo:

- 📅 Programar **clases por colegio, grado, bloque, profesor, materia, libro y unidad** con detección automática de inconsistencias.
- 🎯 Registrar **clases particulares** fuera del horario regular.
- 🚨 Detectar errores de programación en tiempo real (**duplicados, choques de profesor, saltos de secuencia**) con un motor de auditoría dedicado.
- 📝 Generar **informes pedagógicos** vinculados a cada sesión de clase.
- 💵 Liquidar **pagos semanales a profesores** con tarifas por colegio/año y registro inmutable.
- 📊 Exportar **archivos Excel** de horarios y pagos generados completamente en memoria.
- 🔌 Exponer una **API REST documentada** (Swagger / ReDoc) para integraciones externas (sistema financiero).
- 📱 Funcionar como **PWA**: instalable en móvil con manifest, service worker y diseño responsive.

> **Idioma:** Español (Colombia) · **Zona horaria:** America/Bogota · **Moneda:** COP

---

## 🚀 Características principales

### 🗓️ Programación visual

- **Vista general**: calendario unificado de todos los colegios activos, agrupado por colegio → grado → bloque, con caché HTML por mes (10 min).
- **Dashboard por colegio**: matriz `grado × fecha` editable inline con HTMX. Incluye recálculo automático de secuencia cuando se mueven clases.
- **Recomendación inteligente** de la siguiente unidad al programar una clase, considerando libro asignado, fecha y socializaciones.

### 🎯 Catálogo modular

- **Colegio ↔ Colegio-Año**: separación entre datos invariantes (nombre, ciudad…) y datos anuales (tarifa por hora, activo/inactivo) que permite mantener historial sin duplicar registros.
- **Libros normales vs. material asignado**: dos categorías con flujos distintos.
- **Asignaciones por rango de fechas**: un grado puede cambiar de libro a mitad de año sin perder consistencia.

### 🚨 Auditoría automática

| Tipo de alerta | Detecta |
|----------------|---------|
| 🔁 **Duplicado** | Misma unidad de la misma materia programada >1 vez en el mismo `(colegio, grado, libro)` |
| ⚔️ **Conflicto** | Un profesor con clases en >1 colegio el mismo día |
| 📉 **Secuencia** | Salto en la numeración de unidades (ej. pasó de 2 a 4) |

- Deduplicación por **hash MD5** → no se crean alertas repetidas.
- Reactivación automática si un error reaparece (salvo que el admin la haya ignorado manualmente).
- Throttle de 5 minutos para evitar barridos concurrentes a la BD.
- Comando de cron: `python manage.py ejecutar_auditoria`.

### 📝 Informes pedagógicos

- Un `Informe` está vinculado a **exactamente una** clase regular o particular (garantizado por `CheckConstraint` a nivel BD).
- Datos de cabecera **desnormalizados** para sobrevivir aunque se elimine la clase original.
- Estados: borrador → completado (al rellenar `actividades`).

### 💵 Liquidación de pagos

- Cálculo `horas × ColegioAnio.valor_hora` por profesor / colegio / fecha.
- Registro `PagoRealizado` **inmutable** con valor desnormalizado (preserva tarifa histórica).
- Constraint `unique_together (profesor, colegio, fecha)` impide doble liquidación.

### 📊 Exportación Excel

- Generación 100 % en memoria con **openpyxl** (sin tocar disco — ideal para Render).
- ZIPs masivos (un Excel por profesor o por colegio).
- Filtro de URLs `_safe_url()` contra hipervínculos maliciosos en celdas.
- Días/meses **siempre en español**, independiente del locale del SO.

### 📱 Tablero Kanban (home)

Sistema sencillo de pendientes con tres columnas (Pendiente · En gestión · Completado), totalmente operable con HTMX y arrastrable entre estados.

### 🔌 API REST

- JWT con tokens de **8 h (access)** y **7 d (refresh)**.
- Filtros declarativos (`django-filter`), búsqueda full-text en campos clave, paginación configurable (200/página, máx 1000).
- Throttle global `1000/hora/usuario`.
- **Documentación OpenAPI** lista en [`/api/v1/docs/`](http://programacion.lvh.me:8000/api/v1/docs/) (Swagger) y [`/api/v1/redoc/`](http://programacion.lvh.me:8000/api/v1/redoc/), bajo el subdominio del área (`programacion.miltonochoa.app`).

### 📲 PWA

- `manifest.json` y `sw.js` servidos desde la raíz de cada subdominio (scope `/` por origen → cada área es una PWA instalable independiente).
- Instalable como app standalone en móvil.
- Theme color y safe-area-inset para edge-to-edge en iOS/Android.

---

## 🛠️ Stack tecnológico

<table>
<tr><th>Capa</th><th>Tecnología</th><th>Versión</th></tr>
<tr><td>🐍 Backend</td><td>Django</td><td>5.2.11</td></tr>
<tr><td>⚡ Interactividad</td><td>HTMX</td><td>1.9.12</td></tr>
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

## 🏗️ Arquitectura

```
┌──────────────────────────────────────────────────────────────────┐
│                      🌐 Cliente (navegador / PWA)                 │
│   Bootstrap 5 · HTMX · Vanilla JS · Service Worker · Manifest    │
└──────────────────────────┬───────────────────────────────────────┘
                           │ HTTP(S)  ·  <area>.miltonochoa.app
┌──────────────────────────▼───────────────────────────────────────┐
│   🛡️  WhiteNoise · EnrutadoPorArea (subdominio→urlconf) ·         │
│        ControlAcceso (login, scope por rol, perfil inyectado)     │
└──────────────────────────┬───────────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────────────┐
        │                  │                          │
┌───────▼───────┐ ┌────────▼──────────┐ ┌─────────────▼──────────┐
│  📄 Vistas     │ │  🔌 API REST       │ │  ⚙️  Comandos manage   │
│  (HTMX/HTML)  │ │  (DRF + JWT)      │ │  (auditoría, etc.)     │
└───────┬───────┘ └────────┬──────────┘ └─────────────┬──────────┘
        │                  │                          │
        └──────────────────┼──────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│              💾  ORM Django · Signals · Caché (locmem/Redis)      │
│           (invalidación auto: vista_general, auditoría)           │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│   🐘 PostgreSQL (Supabase)            🗃️  SQLite (local/tests)    │
└──────────────────────────────────────────────────────────────────┘
```

**Patrón híbrido HTMX + DRF**: las pantallas internas usan HTML server-rendered con HTMX para interactividad parcial. La API DRF expone los datos al sistema financiero externo con JWT.

---

## 📦 Instalación local

### Requisitos previos

- **Python 3.11+**
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

Para **desarrollo local con SQLite** (sin tocar la BD de producción), crea
`.env.dev-api` en la raíz — se carga **antes** que `.env`. Hay una plantilla en
[`.env.example`](.env.example):

```dotenv
DEBUG=True
DATABASE_URL=sqlite:///db.sqlite3
SECRET_KEY=<genera-una-con-get_random_secret_key>
PASSWORD_ENCRYPT_KEY=<clave-fernet>
ALLOWED_HOSTS=localhost,127.0.0.1
SECURE_SSL_REDIRECT=False
CACHE_BACKEND=locmem
```

Para generar una `SECRET_KEY`:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

(Para producción se usa `.env` con `DATABASE_URL` de PostgreSQL — ver
[Variables de entorno](#️-variables-de-entorno).)

### 3 · Migrar y crear superusuario

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 4 · (Opcional) Cargar el backup de datos

El proyecto incluye un importador del Excel de respaldo (`backups/AAMO_export.xlsx`,
17 hojas con toda la BD). Sobre una BD ya migrada:

```bash
python manage.py importar_backup backups/AAMO_export.xlsx
```

Preserva los ids originales, es idempotente (`update_or_create`) y conserva las
marcas de tiempo del backup. **Nota:** las contraseñas no vienen en el Excel; los
usuarios importados quedan con contraseña inutilizable — entra con el superusuario
creado en el paso 3 o resetéalas.

### 5 · Levantar el servidor

```bash
python manage.py runserver
```

**Enrutado por subdominios.** Cada área se sirve en su propio subdominio. En dev
usamos `lvh.me` (y `*.lvh.me`), que resuelven a `127.0.0.1` sin tocar el archivo
`hosts` — basta con `BASE_DOMAIN=lvh.me` en `.env.dev-api`:

| Host (dev)                          | Sirve                                   |
|-------------------------------------|-----------------------------------------|
| `http://lvh.me:8000/`               | **Apex**: login único + selector de área |
| `http://programacion.lvh.me:8000/`  | **Área programacion** (Kanban, colegios, API…) |

🌐 Abrir [http://lvh.me:8000](http://lvh.me:8000) → login en `/usuarios/login/` →
tras entrar, el sistema redirige al **subdominio** del área del usuario
(`http://programacion.lvh.me:8000/` para el superusuario). La sesión se comparte
en `.lvh.me`, así un solo login vale para todos los subdominios (SSO).

---

## ⚙️ Variables de entorno

| Variable                | Obligatoria | Default              | Descripción                                                              |
|-------------------------|:-----------:|----------------------|--------------------------------------------------------------------------|
| `SECRET_KEY`            | ✅          | —                    | Clave secreta de Django. Sin ella la app no arranca.                     |
| `DEBUG`                 | ❌          | `False`              | `True` para desarrollo local.                                            |
| `ALLOWED_HOSTS`         | ❌          | `localhost,127.0.0.1`| Hosts extra (CSV). El apex y `.BASE_DOMAIN` se añaden solos.             |
| `BASE_DOMAIN`           | ❌          | `miltonochoa.app`    | Dominio base del enrutado por subdominios (dev: `lvh.me`).               |
| `PASSWORD_ENCRYPT_KEY`  | ✅          | —                    | Clave Fernet para datos sensibles.                                       |
| `DATABASE_URL`          | ✅          | —                    | URL completa de PostgreSQL (Supabase, Render…).                          |
| `SECURE_SSL_REDIRECT`   | ❌          | `False`              | `True` en producción si el dominio sirve HTTPS.                          |
| `CACHE_BACKEND`         | ❌          | `locmem`             | `locmem` o `redis`.                                                      |
| `REDIS_URL`             | ⚠️          | `redis://127.0.0.1:6379/1` | Solo si `CACHE_BACKEND=redis`.                                  |
| `BACKUP_DIR`            | ❌          | `backups/` (en la raíz) | Directorio para backups (`BASE_DIR/backups`).                         |

> 💡 Si existe `.env.dev-api` se carga **antes** del `.env`. Sirve para usar SQLite local sin tocar la config de producción.

---

## 🧭 Estructura del proyecto

**AAMO** es un solo proyecto Django organizado por **áreas** (subcarpetas). Hoy
solo `programacion/` está implementada; `logistica/` y `financiera/` son
placeholders listos para crecer. El login es único y, según permisos, redirige
al área del usuario.

```
AAMO/
│
├── 🧩 core/                  # Motor: settings, URLs raíz (router de áreas), seleccion_area
├── 👥 usuarios/              # GLOBAL: login único, perfiles, middleware de acceso, rate-limit
│
├── 📚 programacion/          # ÁREA programacion (paquete Python) — servida en programacion.miltonochoa.app
│   ├── urls.py               #   router del área (agrupa las sub-apps)
│   ├── 🗂️  configuracion/     #   Catálogos: Materia, Libro, Unidad, Colegio, ColegioAnio, Profesor
│   │      └── management/commands/importar_backup.py   # importador del Excel de respaldo
│   ├── 🏫 colegios/          #   Grado, Bloque, Asignacion, Clase, ClaseParticular, HistorialCambio
│   ├── 👨‍🏫 profesores/         #   Vista de horario propio del profesor
│   ├── 🚨 auditoria/         #   Motor de detección de errores + AlertaAuditoria + cron command
│   ├── 📝 informes/          #   Informes pedagógicos por sesión
│   ├── 📊 exportar/          #   Generación de Excel + modelo PagoRealizado
│   ├── 📋 pendientes/        #   Tablero Kanban (home del área)
│   └── 🔌 api/               #   DRF: serializers, viewsets, urls, paginación, tests
│
├── 🚚 logistica/             # PLACEHOLDER de área futura (solo __init__.py + README)
├── 💰 financiera/            # PLACEHOLDER de área futura (solo __init__.py + README)
│
├── 🎨 templates/             # Globales: base.html, home, 404, 500, login, seleccion_area, sw.js
├── 📜 logs/                  # Rotating file handler (5MB × 5 backups, gitignored)
├── 💾 backups/               # AAMO_export.xlsx (respaldo de BD; gitignored salvo este)
│
├── 🚀 manage.py              # Entry point Django (apunta a core.settings)
├── 📦 requirements.txt       # Dependencias de producción
├── 🛠️  requirements-dev.txt  # Adicionales de desarrollo y testing
├── 🔒 .env / .env.dev-api    # Variables locales (gitignored; .env.dev-api → SQLite local)
├── 📄 README.md              # Este archivo
└── 🤖 CLAUDE.md              # Guía para sesiones de Claude Code
```

> **Etiquetas (`app_label`) conservadas:** aunque las apps viven dentro de
> `programacion/`, sus labels siguen siendo `configuracion`, `colegios`, etc.
> (definidas en cada `apps.py`). Por eso las migraciones, tablas y FKs por
> string (`'configuracion.Colegio'`) no cambiaron al unificar el proyecto.

---

## 🔐 Roles y control de acceso

**Login único + selección de área por subdominio:** todos entran por el **apex**
(`miltonochoa.app/usuarios/login/`). Tras autenticarse, `core.views.seleccion_area`
/ `usuarios.views.login_redirect` miran las áreas del usuario (vía el grupo
`area:programacion` o un perfil de colegio/profesor; el superusuario tiene todas)
y redirigen al **subdominio** del área (`programacion.miltonochoa.app`); si tiene
varias, muestra un selector; si no tiene ninguna, un mensaje claro. Si alguien
entra directo a un subdominio sin sesión, se le envía al login del apex y de ahí,
según permisos, a su área. La sesión se comparte en `.miltonochoa.app` (SSO).

El middleware de host [`core/middleware.py`](core/middleware.py) elige el `urlconf`
según el subdominio (`request.area`); el de acceso
[`usuarios/middleware.py`](usuarios/middleware.py) impone scope por rol **dentro
del subdominio del área** (en el apex deja pasar — sus vistas usan decoradores):

| Rol                    | Vinculación                  | Rutas permitidas (en `programacion.miltonochoa.app`) | Atributos inyectados en `request`              |
|------------------------|------------------------------|------------------------------------------------------|------------------------------------------------|
| 👑 **Superusuario**    | `User.is_superuser=True`     | Todo                                                 | `perfil_colegio=None`, `perfil_profesor=None`  |
| 🏫 **Gestor colegio**  | `UsuarioColegio` (OneToOne)  | `/colegios/`, `/informes/`                           | `perfil_colegio`, `colegio_anio_activo`        |
| 👨‍🏫 **Profesor**         | `UsuarioProfesor` (OneToOne) | `/profesores/`, `/informes/`                         | `perfil_profesor`                              |

> ⚠️ Un usuario autenticado **sin perfil/área vinculada** se desloguea automáticamente. El login (`/usuarios/`) y las rutas PWA (`/manifest.json`, `/sw.js`) quedan fuera del scope de área; la API REST usa JWT propio.

**Ratelimit**: el decorador `@rate_limit(max_calls, periodo)` (en `usuarios/ratelimit.py`) protege endpoints sensibles:
- 🔐 Login: **10 intentos / 60 s** por IP.
- 📚 AJAX de unidades/materias: **200 / 60 s**.

---

## 📡 API REST

**Base:** `https://programacion.miltonochoa.app/api/v1/` (la API vive en el
subdominio del área; en dev, `http://programacion.lvh.me:8000/api/v1/`).

### 🔑 Autenticación

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

| Token   | Vigencia |
|---------|----------|
| Access  | 8 horas  |
| Refresh | 7 días   |

### 📚 Documentación interactiva

| Recurso          | URL                                                                                  |
|------------------|--------------------------------------------------------------------------------------|
| 🧪 Swagger UI     | [`/api/v1/docs/`](http://programacion.lvh.me:8000/api/v1/docs/)                                |
| 📖 ReDoc          | [`/api/v1/redoc/`](http://programacion.lvh.me:8000/api/v1/redoc/)                              |
| 📄 OpenAPI schema | [`/api/v1/schema/`](http://programacion.lvh.me:8000/api/v1/schema/)                            |

### 🛣️ Endpoints disponibles

| Recurso                          | Métodos | Descripción                                                  |
|----------------------------------|---------|--------------------------------------------------------------|
| `/api/v1/profesores/`            | `GET`   | Listado de profesores con filtros y búsqueda                 |
| `/api/v1/colegios/`              | `GET`   | Catálogo base de colegios                                    |
| `/api/v1/colegios-anio/`         | `GET`   | Instancias anuales con `valor_hora`                          |
| `/api/v1/clases/`                | `GET`   | Clases programadas (filtros: desde/hasta, profesor, colegio) |
| `/api/v1/clases-particulares/`   | `GET`   | Clases particulares                                           |
| `/api/v1/pagos/`                 | `GET`, `POST` | Pagos realizados — crear marca `marcado_por=request.user` |

**Paginación**: 200/página por defecto, `?page_size=N` (max 1000).
**Throttle**: `1000/hora/usuario`.

---

## 🧪 Tests y calidad

```bash
# Ejecutar toda la suite (usa SQLite en test_db.sqlite3)
python manage.py test

# Tests de una app específica
python manage.py test api
python manage.py test colegios
python manage.py test auditoria

# Cobertura (requiere coverage)
coverage run --source='.' manage.py test
coverage report -m
coverage html  # → htmlcov/index.html
```

**Convenciones**:
- Tests con `unittest`/`Django TestCase` (no pytest todavía, aunque está disponible).
- BD de tests siempre SQLite — forzado en `core/settings.py` cuando `'test' in sys.argv`.
- Cobertura objetivo: **80 %** en `api/`, `auditoria/`, `colegios/`, `usuarios/`.

**Herramientas dev disponibles** (ver `requirements-dev.txt`):

- 🐛 `django-debug-toolbar` — panel de SQL/templates/signals
- 🔬 `django-extensions` — `shell_plus`, `runserver_plus`, `graph_models`
- 🧵 `django-silk` — profiling de queries y request timing
- 🏭 `factory-boy` — fixtures declarativos

---

## ☁️ Despliegue en producción

Despliegue continuo: **push a `main` en GitHub → deploy automático en Railway**.
Base de datos gestionada en **Supabase** (PostgreSQL). El dominio definitivo es
`miltonochoa.app`, con cada área en su subdominio.

### 1 · Base de datos (Supabase)

1. Crea un proyecto en Supabase.
2. Copia la cadena de conexión del **Session pooler** (puerto `5432`):
   `postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres`.
   (Settings ya fuerza SSL en producción vía `dj_database_url(ssl_require=not DEBUG)`.)

### 2 · App (Railway)

1. **New Project → Deploy from GitHub repo** y selecciona este repositorio.
   Railway construye con **Nixpacks** y respeta [`railway.json`](railway.json):
   en cada deploy ejecuta `migrate` → `collectstatic` → `gunicorn`.
2. **Auto-deploy:** en *Settings → Service*, deja el branch de despliegue en `main`.
   Cada commit a `main` dispara un nuevo deploy.
3. **Variables** (*Variables*):

   | Variable | Valor |
   |----------|-------|
   | `SECRET_KEY` | (genérala) |
   | `DEBUG` | `False` |
   | `BASE_DOMAIN` | `miltonochoa.app` |
   | `ALLOWED_HOSTS` | `<tu-app>.up.railway.app` *(el apex y `.miltonochoa.app` se añaden solos)* |
   | `DATABASE_URL` | cadena del Session pooler de Supabase |
   | `PASSWORD_ENCRYPT_KEY` | clave Fernet |
   | `SECURE_SSL_REDIRECT` | `True` |
   | `CACHE_BACKEND` | `redis` + `REDIS_URL` *(opcional)* |

### 3 · Dominio y subdominios (DNS + TLS)

En *Settings → Networking → Custom Domain* de Railway añade el apex y cada área,
y crea los registros DNS que Railway indique (normalmente `CNAME`):

| Dominio | Apunta a |
|---------|----------|
| `miltonochoa.app` (apex) | destino de Railway |
| `www.miltonochoa.app` | destino de Railway |
| `programacion.miltonochoa.app` | destino de Railway |
| *(futuro)* `logistica.` / `financiera.` | destino de Railway |

Railway emite el certificado TLS por dominio automáticamente. Todos los hosts
llegan a la **misma** app; `core.middleware.EnrutadoPorAreaMiddleware` decide el
área por el subdominio. Para añadir un área nueva: regístrala en
[`core/areas.py`](core/areas.py), crea su `urlconf` y añade su subdominio aquí.

**Auditoría programada:** crea en Railway un *Cron Service* (o usa el scheduler)
con `python manage.py ejecutar_auditoria` (sugerido cada 30 min).

> ⚠️ Filesystem efímero en Railway — todos los Excel/ZIP se generan en `BytesIO`
> y se devuelven directamente en la respuesta.

**Cabeceras de seguridad activadas con `DEBUG=False`**:
- 🔒 `SECURE_SSL_REDIRECT` (configurable)
- 🍪 `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SESSION_COOKIE_HTTPONLY`
- 🛡️ `SECURE_CONTENT_TYPE_NOSNIFF`
- ⏳ HSTS 1 año con `includeSubDomains` y `preload`
- 🪟 `XFrameOptions` (clickjacking)

---

## 🩹 Mantenimiento

### Comandos útiles

```bash
# Crear migraciones tras cambios en modelos
python manage.py makemigrations
python manage.py migrate

# Auditoría manual (ignora throttle de 5 min)
python manage.py ejecutar_auditoria

# Recolectar estáticos antes de desplegar
python manage.py collectstatic --noinput

# Shell con autoload de modelos (django-extensions)
python manage.py shell_plus

# Ver SQL de una migración sin aplicarla
python manage.py sqlmigrate <app> <numero>
```

### Logs

- Rotating file handler: `logs/app.log` (5 MB × 5 backups).
- Logger principal: `aamo` (DEBUG en dev, INFO en prod).
- En `DEBUG=True` también va a consola.

### Caché

Si trabajas en `vista_general` o `auditoria/engine.py`, recuerda invalidar la caché (los signals de `colegios/signals.py` lo hacen al modificar `Clase`/`Asignacion`).

---

## 🤝 Contribuir

1. Crea una rama desde `main`: `git checkout -b feat/mi-feature`.
2. Sigue las convenciones de comentarios del repo: explica el **porqué** de decisiones no obvias, no el **qué**.
3. Añade/actualiza tests en la app correspondiente (`apps/<nombre>/tests.py` o `api/tests/`).
4. Ejecuta `python manage.py test` y verifica que pase todo.
5. Si tocas modelos, **incluye la migración** en el commit.
6. Abre un PR contra `main` con una descripción clara del cambio y su motivación.

> 📖 Si modificas algo estructural (rutas, modelos, signals, caché), **actualiza también [`CLAUDE.md`](CLAUDE.md)** para mantener la guía interna sincronizada.

---

## 📜 Licencia

Este proyecto es **de uso interno** de la organización **Milton Ochoa / AAMO**. No está licenciado para distribución pública.

---

<div align="center">

**Hecho con ❤️ por el equipo AAMO**

<sub>© 2026 Programación AAMO · Versión Web</sub>

</div>
