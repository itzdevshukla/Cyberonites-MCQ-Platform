"""
Development-specific Django settings.
Uses InMemoryChannelLayer (no Redis needed locally).
"""
from .base import *  # noqa: F401, F403

DEBUG = True
ALLOWED_HOSTS = ['*']

# Django Channels & Cache inherit dynamically from base.py (uses Redis if REDIS_URL exists, else InMemory fallback)

# Email backend for development
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Disable security features for local development
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Ultra-fast in-memory cache for development (eliminates 4s Redis socket timeout delays)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'cyberonites-dev-cache',
    }
}

STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}

