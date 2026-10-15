"""
Production-specific Django settings.
Configured for Render deployment with Redis and persistent disk.
"""
import os
from .base import *  # noqa: F401, F403

DEBUG = False
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=[
    'qarena.abhirajsinghchauhan.in',
    'abhirajsinghchauhan.in',
    'www.abhirajsinghchauhan.in',
    '13.205.208.223',
    '13.126.227.185',
    'localhost',
    '127.0.0.1',
])

# Database — AWS RDS / EC2 PostgreSQL OR DATABASE_URL OR SQLite fallback
if os.environ.get('DATABASE_URL'):
    try:
        import dj_database_url
        DATABASES['default'] = dj_database_url.config(
            conn_max_age=env.int('DB_CONN_MAX_AGE', default=60),
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
            'CONN_MAX_AGE': env.int('DB_CONN_MAX_AGE', default=60),
            'CONN_HEALTH_CHECKS': True,
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

# Security — Production hardening for AWS / Production HTTPS
SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=True)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = 'DENY'

# Cookies Hardening — BUG-09 FIX: Enforce Secure HTTPS cookies by default
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=True)
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=True)
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # Needed for AJAX
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'

# CSRF trusted origins for AWS EC2 / RDS / Domains (strict origins only)
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[
    'https://qarena.abhirajsinghchauhan.in',
    'http://qarena.abhirajsinghchauhan.in',
    'https://abhirajsinghchauhan.in',
    'https://www.abhirajsinghchauhan.in',
    'http://13.205.208.223',
    'http://13.126.227.185',
    'http://localhost:8000',
    'http://127.0.0.1:8000',
])

# Logging — Production (route to console/journalctl to avoid file permission errors)
LOGGING['handlers']['console']['level'] = 'INFO'
LOGGING['loggers']['django']['level'] = 'WARNING'
LOGGING['loggers']['quiz']['handlers'] = ['console']
LOGGING['loggers']['accounts']['handlers'] = ['console']
