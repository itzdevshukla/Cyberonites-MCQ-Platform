"""
WSGI config for Quiz Platform.
"""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quiz_platform.settings.development')
application = get_wsgi_application()
