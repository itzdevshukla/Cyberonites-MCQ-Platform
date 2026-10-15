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
        user = self.scope.get('user')
        if not user or not user.is_authenticated:
            logger.warning("Unauthenticated WebSocket connection rejected on LeaderboardConsumer")
            await self.close(code=4001)
            return

        self.quiz_id = self.scope['url_route']['kwargs']['quiz_id']
        self.group_name = f'leaderboard_{self.quiz_id}'

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Send initial leaderboard data
        payload = await self._get_leaderboard_payload()
        await self.send(text_data=json.dumps({
            'type': 'leaderboard_update',
            **payload,
        }))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def leaderboard_update(self, event):
        """Broadcast leaderboard update to all connected clients without DB stampede."""
        entries = event.get('entries')
        if entries is None:
            payload = await self._get_leaderboard_payload()
        else:
            payload = {
                'entries': entries,
                'total_joined': event.get('total_joined'),
                'total_submitted': event.get('total_submitted'),
                'top_score': event.get('top_score'),
            }
        await self.send(text_data=json.dumps({
            'type': 'leaderboard_update',
            **payload,
        }))

    @database_sync_to_async
    def _get_leaderboard_payload(self):
        from quiz.models import Quiz
        from .services import LeaderboardService
        try:
            quiz = Quiz.objects.get(id=self.quiz_id)
            entries = LeaderboardService.get_leaderboard(quiz)
            total_joined = quiz.participations.count()
            total_submitted = quiz.participations.filter(is_submitted=True).count()
            top_score = entries[0]['score'] if entries else 0
            return {
                'entries': entries,
                'total_joined': total_joined,
                'total_submitted': total_submitted,
                'top_score': top_score,
            }
        except Quiz.DoesNotExist:
            return {
                'entries': [],
                'total_joined': 0,
                'total_submitted': 0,
                'top_score': 0,
            }
