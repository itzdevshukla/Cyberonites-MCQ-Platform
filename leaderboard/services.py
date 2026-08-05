"""
Leaderboard calculation and caching service.
"""
import logging
from django.db.models import F

from .models import LeaderboardEntry

from django.db import transaction, models

logger = logging.getLogger('quiz')


class LeaderboardService:
    """
    Handles leaderboard calculation and ranking.
    Ranking rules: Score DESC → Time ASC → Wrong Answers ASC.
    """

    @staticmethod
    def recalculate_ranks(quiz):
        """
        Recalculate all ranks for a quiz with atomic transaction locking.
        Called after each submission.
        """
        with transaction.atomic():
            entries = LeaderboardEntry.objects.select_for_update().filter(quiz=quiz).order_by(
                '-score',       # Higher score first
                'time_taken',   # Less time first
                'wrong_answers' # Fewer wrong answers first
            )

            for rank, entry in enumerate(entries, start=1):
                if entry.rank != rank:
                    entry.rank = rank
                    entry.save(update_fields=['rank'])

        logger.info(f"Recalculated ranks for quiz '{quiz.title}': {entries.count()} entries")


        # Broadcast live update to all WebSocket clients on leaderboard page
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            channel_layer = get_channel_layer()
            if channel_layer:
                async_to_sync(channel_layer.group_send)(
                    f'leaderboard_{quiz.id}',
                    {'type': 'leaderboard_update'}
                )
        except Exception as e:
            logger.error(f"Failed to broadcast leaderboard WebSocket update: {e}")


    @staticmethod
    def get_leaderboard(quiz, limit=100):
        """
        Get leaderboard data for a quiz.
        Uses select_related for efficient queries.
        """
        entries = LeaderboardEntry.objects.filter(
            quiz=quiz
        ).select_related('participant').order_by('rank')[:limit]

        return [
            {
                'rank': entry.rank,
                'name': entry.participant.full_name if entry.participant else 'Deleted User',
                'college': entry.participant.college if entry.participant else 'N/A',
                'score': entry.score,
                'accuracy': entry.accuracy,
                'time_taken': entry.time_taken,
                'questions_attempted': entry.questions_attempted,
                'correct_answers': entry.correct_answers,
                'wrong_answers': entry.wrong_answers,
                'participant_id': entry.participant.id if entry.participant else 0,
            }
            for entry in entries
        ]


    @staticmethod
    def get_participant_rank(quiz, participant):
        """Get a specific participant's rank and stats."""
        try:
            entry = LeaderboardEntry.objects.get(quiz=quiz, participant=participant)
            total = LeaderboardEntry.objects.filter(quiz=quiz).count()
            return {
                'rank': entry.rank,
                'total_participants': total,
                'score': entry.score,
                'accuracy': entry.accuracy,
                'time_taken': entry.time_taken,
            }
        except LeaderboardEntry.DoesNotExist:
            return None
