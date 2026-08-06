"""
Production-specific Django settings.
Configured for Render deployment with Redis and persistent disk.
"""
import os
from .base import *  # noqa: F401, F403

DEBUG = False
ALLOWED_HOSTS = env('ALLOWED_HOSTS', default=['*'])

# Database — AWS RDS / EC2 PostgreSQL OR DATABASE_URL OR SQLite fallback
if os.environ.get('DATABASE_URL'):
    try:
        import dj_database_url
        DATABASES['default'] = dj_database_url.config(
            conn_max_age=600,
            conn_health_checks=True,
        )
    except ImportError:
        pass
elif os.environ.get('POSTGRES_DB'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('POSTGRES_DB', 'cyberonites_db'),
            'USER': os.environ.get('POSTGRES_USER', 'cyberonites_user'),
            'PASSWORD': os.environ.get('POSTGRES_PASSWORD', ''),
            'HOST': os.environ.get('POSTGRES_HOST', 'localhost'),
            'PORT': os.environ.get('POSTGRES_PORT', '5432'),
            'CONN_MAX_AGE': 600,
            'OPTIONS': {
                'connect_timeout': 10,
            }
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
            'OPTIONS': {
                'timeout': 20,
            }
        }
    }

# Django Channels — Redis if REDIS_URL provided, else InMemory
if os.environ.get('REDIS_URL'):
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                'hosts': [os.environ.get('REDIS_URL')],
                'capacity': 1500,
                'expiry': 10,
            },
        },
    }
else:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        },
    }

# Cache — Redis (if available) or LocMem
if os.environ.get('REDIS_URL'):
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': os.environ.get('REDIS_URL'),
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            },
        },
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    }

# Security — Production hardening for AWS
SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=False)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = 'DENY'

# Cookies Hardening
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=False)
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=False)
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # Needed for AJAX
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'

# CSRF trusted origins for AWS EC2 / RDS / Domains
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=['http://*', 'https://*'])

# Logging — Production
LOGGING['handlers']['console']['level'] = 'INFO'
LOGGING['loggers']['django']['level'] = 'WARNING'
