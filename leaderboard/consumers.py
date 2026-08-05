"""
WebSocket consumer for live leaderboard updates.
"""
import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

logger = logging.getLogger('quiz')


class LeaderboardConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for live leaderboard.
    Group: leaderboard_{quiz_id}
    """

    async def connect(self):
        self.quiz_id = self.scope['url_route']['kwargs']['quiz_id']
        self.group_name = f'leaderboard_{self.quiz_id}'

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Send initial leaderboard data
        data = await self._get_leaderboard_data()
        await self.send(text_data=json.dumps({
            'type': 'leaderboard_update',
            'entries': data,
        }))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def leaderboard_update(self, event):
        """Broadcast leaderboard update to all connected clients."""
        data = await self._get_leaderboard_data()
        await self.send(text_data=json.dumps({
            'type': 'leaderboard_update',
            'entries': data,
        }))

    @database_sync_to_async
    def _get_leaderboard_data(self):
        from quiz.models import Quiz
        from .services import LeaderboardService
        try:
            quiz = Quiz.objects.get(id=self.quiz_id)
            return LeaderboardService.get_leaderboard(quiz)
        except Quiz.DoesNotExist:
            return []
