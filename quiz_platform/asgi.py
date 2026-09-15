"""
ASGI config for Quiz Platform.
Handles both HTTP and WebSocket protocols.
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quiz_platform.settings.development')
django.setup()

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

from quiz.routing import websocket_urlpatterns as quiz_ws
from leaderboard.routing import websocket_urlpatterns as leaderboard_ws

application = ProtocolTypeRouter({
    'http': get_asgi_application(),
    'websocket': AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(
                quiz_ws + leaderboard_ws
            )
        )
    ),
})
