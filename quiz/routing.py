"""
WebSocket URL routing for quiz app.
"""
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/quiz/(?P<quiz_id>\d+)/$', consumers.QuizConsumer.as_asgi()),
]
