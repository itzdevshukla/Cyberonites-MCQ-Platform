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
    Optimized for high-concurrency (200+ users) without database row locking.
    """

    @staticmethod
    def recalculate_ranks(quiz):
        """
        Recalculate all ranks for a quiz using bulk_update without table row locking.
        """
        entries = list(LeaderboardEntry.objects.filter(quiz=quiz).order_by(
            '-score',       # Higher score first
            'time_taken',   # Less time first
            'wrong_answers' # Fewer wrong answers first
        ))

        updated_entries = []
        for rank, entry in enumerate(entries, start=1):
            if entry.rank != rank:
                entry.rank = rank
                updated_entries.append(entry)

        if updated_entries:
            LeaderboardEntry.objects.bulk_update(updated_entries, ['rank'], batch_size=200)

        logger.info(f"Recalculated ranks for quiz '{quiz.title}': {len(entries)} entries")

        # Broadcast live update to all WebSocket clients on leaderboard page
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            channel_layer = get_channel_layer()
            if channel_layer:
                entries_data = LeaderboardService.get_leaderboard(quiz)
                total_joined = quiz.participations.count()
                total_submitted = quiz.participations.filter(is_submitted=True).count()
                top_score = entries_data[0]['score'] if entries_data else 0
                async_to_sync(channel_layer.group_send)(
                    f'leaderboard_{quiz.id}',
                    {
                        'type': 'leaderboard_update',
                        'entries': entries_data,
                        'total_joined': total_joined,
                        'total_submitted': total_submitted,
                        'top_score': top_score,
                    }
                )
        except Exception as e:
            logger.error(f"Failed to broadcast leaderboard WebSocket update: {e}")


    @staticmethod
    def get_leaderboard(quiz, limit=500):
        """
        Get leaderboard data for a quiz.
        Uses select_related and dynamic rank assignment for zero-lock reads.
        """
        qs = LeaderboardEntry.objects.filter(
            quiz=quiz
        ).select_related('participant').order_by(
            '-score',
            'time_taken',
            'wrong_answers'
        )
        entries = qs[:limit] if limit else qs

        return [
            {
                'rank': rank,
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
            for rank, entry in enumerate(entries, start=1)
        ]
    @staticmethod
    def get_leaderboard_iterator(quiz, chunk_size=500):
        """
        Streaming generator for leaderboard entries.
        Uses database cursor chunking (iterator) to maintain flat O(1) memory overhead
        regardless of participant count (safe for 10,000+ entries).
        """
        qs = LeaderboardEntry.objects.filter(
            quiz=quiz
        ).select_related('participant').order_by(
            '-score',
            'time_taken',
            'wrong_answers'
        )

        for rank, entry in enumerate(qs.iterator(chunk_size=chunk_size), start=1):
            yield {
                'rank': rank,
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

    @staticmethod
    def get_participant_rank(quiz, participant):
        """
        Get a specific participant's rank and stats via lockless indexed SQL query.
        Rank = 1 + count of participants with higher score (or faster time).
        """
        try:
            entry = LeaderboardEntry.objects.get(quiz=quiz, participant=participant)
            # Lockless O(log N) count query
            higher_count = LeaderboardEntry.objects.filter(
                models.Q(score__gt=entry.score) |
                models.Q(score=entry.score, time_taken__lt=entry.time_taken) |
                models.Q(score=entry.score, time_taken=entry.time_taken, wrong_answers__lt=entry.wrong_answers),
                quiz=quiz
            ).count()

            rank = higher_count + 1
            total = LeaderboardEntry.objects.filter(quiz=quiz).count()
            return {
                'rank': rank,
                'total_participants': total,
                'score': entry.score,
                'accuracy': entry.accuracy,
                'time_taken': entry.time_taken,
            }
        except LeaderboardEntry.DoesNotExist:
            return None
