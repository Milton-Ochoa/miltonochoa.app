"""
Django settings for core project.
"""

from pathlib import Path
import os
import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv
import sys

# Cargar variables del .env (una sola vez)
# Prioridad: .env.dev-api > .env (default)
# Esto permite trabajar en BD local SQLite sin tocar config de prod en .env
BASE_DIR = Path(__file__).resolve().parent.parent
_DEV_API_ENV = BASE_DIR / '.env.dev-api'
if _DEV_API_ENV.exists():
    load_dotenv(dotenv_path=_DEV_API_ENV, override=True)
else:
    load_dotenv(dotenv_path=BASE_DIR / '.env')

# ─────────────────────────────────────────────────────────────
# SEGURIDAD
# ─────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise ImproperlyConfigured(
        "Falta SECRET_KEY en el .env. Genera una con: "
        "python -c \"from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())\""
    )

DEBUG = os.environ.get('DEBUG', 'False') == 'True'

# ── Enrutado por subdominios (áreas) ──
# Cada área se sirve en su propio subdominio: programacion.<BASE_DOMAIN>, etc.
# El apex (<BASE_DOMAIN>) es el login único + selector de área (ver core.middleware).
#   prod:  BASE_DOMAIN=miltonochoa.app
#   dev:   BASE_DOMAIN=lvh.me      (lvh.me y *.lvh.me resuelven a 127.0.0.1)
BASE_DOMAIN = os.environ.get('BASE_DOMAIN', 'miltonochoa.app')

ALLOWED_HOSTS = [h.strip() for h in os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if h.strip()]
# Garantizar el apex y todos sus subdominios (el comodín '.dominio' cubre las áreas).
ALLOWED_HOSTS += [BASE_DOMAIN, '.' + BASE_DOMAIN]

# Sesión y CSRF compartidos entre apex y subdominios → un solo login (SSO real).
SESSION_COOKIE_DOMAIN = '.' + BASE_DOMAIN
CSRF_COOKIE_DOMAIN = '.' + BASE_DOMAIN
# Orígenes de confianza para POST cross-subdominio (formularios del área).
CSRF_TRUSTED_ORIGINS = [
    f'https://{BASE_DOMAIN}',
    f'https://*.{BASE_DOMAIN}',
]
if DEBUG:
    CSRF_TRUSTED_ORIGINS += [f'http://{BASE_DOMAIN}:8000', f'http://*.{BASE_DOMAIN}:8000']

# ── Cabeceras de seguridad HTTP (solo en producción) ──
if not DEBUG:
    # Railway termina TLS en su proxy y reenvía la petición por HTTP interno.
    # Sin esto, request.is_secure() sería False y SECURE_SSL_REDIRECT haría un bucle.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'False') == 'True'
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_HTTPONLY = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# ─────────────────────────────────────────────────────────────
# APLICACIONES
# ─────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_htmx',
    'storages',
    'core',
    'programacion.configuracion',
    'programacion.colegios',
    'programacion.profesores',
    'usuarios',
    'programacion.informes',
    'programacion.auditoria',
    'programacion.exportar',
    'programacion.pagos',
    'programacion.pendientes',
    'programacion.viaticos',
    'programacion.monitores',
    'financiera.viaticos',
    'financiera.pagos',
    'financiera.monitores',
    'logistica.inventario',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    # Selecciona el urlconf según el subdominio (área). Antes de CommonMiddleware.
    'core.middleware.EnrutadoPorAreaMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django_htmx.middleware.HtmxMiddleware',
    'usuarios.middleware.ControlAccesoMiddleware',
]

LOGIN_URL = '/usuarios/login/'

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'programacion.auditoria.context_processors.alertas_vigentes',
                'financiera.viaticos.context_processors.viaticos_pendientes',
                'financiera.pagos.context_processors.pagos_pendientes',
                'financiera.monitores.context_processors.pagos_monitores_pendientes',
                'programacion.pagos.context_processors.pagos_por_revisar',
                'programacion.monitores.context_processors.simulacros_sin_monitor',
                'programacion.monitores.context_processors.pagos_monitores_por_revisar',
                'logistica.inventario.context_processors.alertas_inventario',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'

# ─────────────────────────────────────────────────────────────
# BASE DE DATOS
# ─────────────────────────────────────────────────────────────
# CONN_MAX_AGE configurable por env. En producción DATABASE_URL apunta al
# **transaction pooler de Supavisor** (puerto 6543) con CONN_MAX_AGE=600: la
# conexión Django→pooler puede ser persistente (baja TTFB) porque es el pooler
# quien multiplexa hacia los backends por transacción. Lo que sí exige el modo
# transaction es DISABLE_SERVER_SIDE_CURSORS=True (cada transacción puede ir a
# un backend distinto y los cursores server-side no sobreviven el salto).
# Ver CLAUDE.md ("Rendimiento y concurrencia en producción") / .env.example.
_CONN_MAX_AGE = int(os.environ.get('CONN_MAX_AGE', '600'))
DATABASES = {
    'default': dj_database_url.config(
        default=os.environ.get('DATABASE_URL'),
        conn_max_age=_CONN_MAX_AGE,
        ssl_require=not DEBUG,  # SSL solo en produccion
    )
}
# Server-side cursors son incompatibles con pgbouncer en modo transaction.
# Se desactivan vía env solo cuando se apunta al pooler transaccional.
if os.environ.get('DISABLE_SERVER_SIDE_CURSORS', 'False').lower() in ('1', 'true', 'yes'):
    DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = True

# ─────────────────────────────────────────────────────────────
# VALIDACIÓN DE CONTRASEÑAS
# ─────────────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ─────────────────────────────────────────────────────────────
# INTERNACIONALIZACIÓN
# ─────────────────────────────────────────────────────────────
LANGUAGE_CODE = 'es-co'
TIME_ZONE = 'America/Bogota'
USE_I18N = True
USE_L10N = True
USE_TZ = True

# ─────────────────────────────────────────────────────────────
# CACHÉ
# Configurable via env: CACHE_BACKEND=locmem (dev) | redis (prod)
# Para Redis: pip install django-redis y agregar REDIS_URL al .env
# ─────────────────────────────────────────────────────────────
_CACHE_BACKEND = os.environ.get('CACHE_BACKEND', 'locmem')

if _CACHE_BACKEND == 'redis':
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379/1'),
            'OPTIONS': {'CLIENT_CLASS': 'django_redis.client.DefaultClient'},
            'TIMEOUT': 300,
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'aamo-cache',
            'TIMEOUT': 300,
        }
    }

# ─────────────────────────────────────────────────────────────
# BACKUP
# ─────────────────────────────────────────────────────────────
BACKUP_DIR = os.environ.get(
    'BACKUP_DIR',
    str(BASE_DIR / 'backups')  # AAMO/backups/ dentro del proyecto
)

LOG_DIR = BASE_DIR / 'logs'
if not LOG_DIR.exists():
    os.makedirs(LOG_DIR)

# ─────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{levelname}] {asctime} {module}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(BASE_DIR / 'logs' / 'app.log'),
            'maxBytes': 5 * 1024 * 1024,  # 5 MB
            'backupCount': 5,
            'formatter': 'verbose',
            'encoding': 'utf-8',
        },
        'console': {
            'level': 'DEBUG' if DEBUG else 'WARNING',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'] if DEBUG else ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'aamo': {
            'handlers': ['console', 'file'] if DEBUG else ['console'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
    },
}

# ─────────────────────────────────────────────────────────────
# CORREO (Resend vía SMTP)
# ─────────────────────────────────────────────────────────────
# En dev sin credenciales: backend de consola (imprime el correo en la terminal),
# así se prueba el flujo sin enviar nada real. En prod: SMTP de Resend; la API key
# (re_...) va como EMAIL_HOST_PASSWORD en Railway. Cambiar de proveedor es solo
# cambiar estas env vars (cero código).
EMAIL_BACKEND = os.environ.get(
    'EMAIL_BACKEND',
    'django.core.mail.backends.console.EmailBackend' if DEBUG
    else 'django.core.mail.backends.smtp.EmailBackend',
)
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.resend.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True') == 'True'
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', 'resend')  # Resend exige el usuario literal "resend"
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')  # API key re_...
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'AAMO <notificaciones@miltonochoa.app>')

# Destinatario de los avisos de viáticos. El default es un fallback razonable (el correo
# del área); en prod lo fija la env var VIATICOS_NOTIFICAR_A.
VIATICOS_NOTIFICAR_A = os.environ.get('VIATICOS_NOTIFICAR_A', 'financiero@aamocolombia.com')

# Destinatario del aviso de legalización de viáticos enviada (revisión post-pago).
VIATICOS_LEGALIZACION_NOTIFICAR_A = os.environ.get(
    'VIATICOS_LEGALIZACION_NOTIFICAR_A', 'financiero@aamocolombia.com')

# Destinatario del aviso de simulacros próximos sin monitor (command
# avisar_simulacros_proximos, pensado para correr a diario por scheduler).
MONITORES_NOTIFICAR_A = os.environ.get(
    'MONITORES_NOTIFICAR_A', 'programacion@aamocolombia.com')

# Destinatario del aviso de pagos a profesores enviados de programación a financiera
# (mismo patrón que los viáticos). Default = correo del área financiera.
PAGOS_NOTIFICAR_A = os.environ.get('PAGOS_NOTIFICAR_A', 'financiero@aamocolombia.com')

# ─────────────────────────────────────────────────────────────
# ARCHIVOS ESTÁTICOS
# ─────────────────────────────────────────────────────────────
STATIC_URL = 'static/'

STATIC_ROOT = BASE_DIR / 'staticfiles'

# ─────────────────────────────────────────────────────────────
# ARCHIVOS SUBIDOS (MEDIA) Y ALMACENAMIENTO
# ─────────────────────────────────────────────────────────────
# Soportes de pago de viáticos: disco local en dev, Supabase Storage (S3) en prod.
# Django 5.2 prohíbe mezclar STORAGES con STATICFILES_STORAGE/DEFAULT_FILE_STORAGE,
# así que static y default conviven aquí dentro de STORAGES.
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

USE_SUPABASE_STORAGE = os.environ.get('USE_SUPABASE_STORAGE', 'False') == 'True'

STORAGES = {
    'default': (
        {
            'BACKEND': 'storages.backends.s3.S3Storage',
            'OPTIONS': {
                'bucket_name':       os.environ['SUPABASE_BUCKET'],
                'endpoint_url':      os.environ['SUPABASE_S3_ENDPOINT'],
                'region_name':       os.environ['SUPABASE_S3_REGION'],
                'access_key':        os.environ['SUPABASE_S3_ACCESS_KEY'],
                'secret_key':        os.environ['SUPABASE_S3_SECRET_KEY'],
                'addressing_style':  'path',   # Supabase exige path-style
                'default_acl':       None,     # bucket privado
                'querystring_auth':  True,
                'querystring_expire': 600,
                'file_overwrite':    False,    # colisiones → sufijo automático
            },
        }
        if USE_SUPABASE_STORAGE else
        {'BACKEND': 'django.core.files.storage.FileSystemStorage'}
    ),
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

if 'test' in sys.argv:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'test_db.sqlite3',
        }
    }
    # Enrutado por área en tests: apex = 'testserver', área = 'programacion.testserver'.
    BASE_DOMAIN = 'testserver'
    ALLOWED_HOSTS = ['testserver', '.testserver']
    # Sin dominio de cookie en tests: el Client envía la sesión a cualquier host.
    SESSION_COOKIE_DOMAIN = None
    CSRF_COOKIE_DOMAIN = None
    # Estáticos sin manifest en tests: el backend de WhiteNoise (CompressedManifest)
    # exige un staticfiles.json de collectstatic que no existe en el entorno de
    # tests, y haría fallar todo render con {% static %}. El backend plano replica
    # el comportamiento previo (cuando STATICFILES_STORAGE era inerte en Django 5.2).
    STORAGES['staticfiles'] = {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    }

TESTING = len(sys.argv) > 1 and sys.argv[1] == 'test'