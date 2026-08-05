"""
WebSocket consumer for real-time quiz events.
Handles: quiz state changes, timer sync, announcements, violations.
"""
import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

logger = logging.getLogger('quiz')


class QuizConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for quiz events.
    Group: quiz_{quiz_id} — all participants of a quiz.
    """

    async def connect(self):
        self.quiz_id = self.scope['url_route']['kwargs']['quiz_id']
        self.group_name = f'quiz_{self.quiz_id}'

        # Join quiz group
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.info(f"WebSocket connected: quiz_{self.quiz_id}")

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info(f"WebSocket disconnected: quiz_{self.quiz_id}")

    async def receive(self, text_data):
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(text_data)
            msg_type = data.get('type', '')

            if msg_type == 'timer_sync':
                remaining = await self._get_remaining_time()
                await self.send(text_data=json.dumps({
                    'type': 'timer_sync',
                    'remaining_seconds': remaining,
                }))

        except json.JSONDecodeError:
            pass

    # --- Group message handlers ---

    async def quiz_state_change(self, event):
        """Broadcast quiz state change to all participants."""
        await self.send(text_data=json.dumps({
            'type': 'quiz_state_change',
            'status': event['status'],
            'remaining_seconds': event.get('remaining_seconds', 0),
            'message': event.get('message', ''),
        }))

    async def quiz_announcement(self, event):
        """Broadcast announcement to all participants."""
        await self.send(text_data=json.dumps({
            'type': 'announcement',
            'message': event['message'],
            'timestamp': event.get('timestamp', ''),
        }))

    async def quiz_auto_submit(self, event):
        """Notify participants to auto-submit (time expired)."""
        await self.send(text_data=json.dumps({
            'type': 'auto_submit',
            'message': 'Time is up! Your quiz has been auto-submitted.',
        }))

    async def timer_extended(self, event):
        """Notify participants of timer extension."""
        await self.send(text_data=json.dumps({
            'type': 'timer_extended',
            'remaining_seconds': event['remaining_seconds'],
            'extra_minutes': event['extra_minutes'],
            'message': f"Timer extended by {event['extra_minutes']} minutes!",
        }))

    async def participant_joined(self, event):
        """Broadcast participant joined event to admin observers."""
        await self.send(text_data=json.dumps({
            'type': 'participant_joined',
            'participant_id': event['participant_id'],
            'participant_name': event['participant_name'],
            'college': event.get('college', ''),
            'email': event.get('email', ''),
            'active_count': event.get('active_count', 0),
            'total_participants': event.get('total_participants', 0),
            'timestamp': event.get('timestamp', ''),
        }))

    async def participant_submitted(self, event):
        """Broadcast participant submitted event to admin observers."""
        await self.send(text_data=json.dumps({
            'type': 'participant_submitted',
            'participant_id': event['participant_id'],
            'participant_name': event['participant_name'],
            'score': event.get('score', 0),
            'time_taken': event.get('time_taken', 0),
            'active_count': event.get('active_count', 0),
            'submitted_count': event.get('submitted_count', 0),
            'timestamp': event.get('timestamp', ''),
        }))

    async def violation_reported(self, event):
        """Broadcast violation event to admin observers."""
        await self.send(text_data=json.dumps({
            'type': 'violation_reported',
            'participant_id': event['participant_id'],
            'participant_name': event['participant_name'],
            'violation_type': event['violation_type'],
            'details': event.get('details', ''),
            'ip_address': event.get('ip_address', '-'),
            'violation_count': event.get('violation_count', 0),
            'created_at': event.get('created_at', ''),
        }))

    @database_sync_to_async
    def _get_remaining_time(self):
        from .models import Quiz
        from .services import TimerService
        try:
            quiz = Quiz.objects.get(id=self.quiz_id)
            return TimerService.get_remaining_seconds(quiz)
        except Quiz.DoesNotExist:
            return 0
