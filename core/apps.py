from django.apps import AppConfig
from django.db.backends.signals import connection_created


def configure_sqlite_wal(sender, connection, **kwargs):
    if connection.vendor == 'sqlite':
        try:
            with connection.cursor() as cursor:
                cursor.execute('PRAGMA journal_mode=WAL;')
                cursor.execute('PRAGMA synchronous=NORMAL;')
                cursor.execute('PRAGMA busy_timeout=30000;')
        except Exception:
            pass


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    verbose_name = 'Core Utilities'

    def ready(self):
        connection_created.connect(configure_sqlite_wal)
