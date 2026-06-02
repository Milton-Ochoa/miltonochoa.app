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
# Prioridad: .env.dev-api (rama feat/htmx-api-migration) > .env (default)
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
    'rest_framework',
    'rest_framework_simplejwt',
    'drf_spectacular',
    'django_filters',
    'core',
    'programacion.configuracion',
    'programacion.colegios',
    'programacion.profesores',
    'usuarios',
    'programacion.informes',
    'programacion.auditoria',
    'programacion.exportar',
    'programacion.pendientes',
    'programacion.api',
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
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'

# ─────────────────────────────────────────────────────────────
# BASE DE DATOS
# ─────────────────────────────────────────────────────────────
DATABASES = {
    'default': dj_database_url.config(
        default=os.environ.get('DATABASE_URL'),
        conn_max_age=600,
        ssl_require=not DEBUG,  # SSL solo en produccion
    )
}

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
# ARCHIVOS ESTÁTICOS
# ─────────────────────────────────────────────────────────────
STATIC_URL = 'static/'

STATIC_ROOT = BASE_DIR / 'staticfiles'

STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ─────────────────────────────────────────────────────────────
# REST FRAMEWORK (DRF)
# ─────────────────────────────────────────────────────────────
from datetime import timedelta  # noqa: E402

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'programacion.api.pagination.StandardPagination',
    'PAGE_SIZE': 200,
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.UserRateThrottle',
        'rest_framework.throttling.AnonRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'user': '1000/hour',
        # El endpoint de obtención de token JWT (auth/token/) es anónimo por
        # naturaleza; sin esto no tendría throttle de DRF. Límite conservador.
        'anon': '30/hour',
    },
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=8),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': False,
    'ALGORITHM': 'HS256',
    'AUTH_HEADER_TYPES': ('Bearer',),
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'AAMO API',
    'DESCRIPTION': 'API REST para sistema de gestión de colegios AAMO. Uso interno y sistema financiero.',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'SERVE_AUTHENTICATION': ['rest_framework.authentication.SessionAuthentication'],
}

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

TESTING = len(sys.argv) > 1 and sys.argv[1] == 'test'