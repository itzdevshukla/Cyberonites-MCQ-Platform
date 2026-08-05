"""
Leaderboard model for ranking participants.
"""
from django.db import models
from django.conf import settings
from core.models import TimeStampedModel


class LeaderboardEntry(TimeStampedModel):
    """
    Cached leaderboard entry for quick ranking.
    Ranking rules: Score DESC → Time ASC → Wrong Answers ASC.
    """

    quiz = models.ForeignKey('quiz.Quiz', on_delete=models.CASCADE, related_name='leaderboard_entries')
    participant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='leaderboard_entries'
    )
    rank = models.PositiveIntegerField(default=0)
    score = models.FloatField(default=0)
    accuracy = models.FloatField(default=0, help_text="Percentage")
    time_taken = models.FloatField(default=0, help_text="Seconds")
    questions_attempted = models.PositiveIntegerField(default=0)
    correct_answers = models.PositiveIntegerField(default=0)
    wrong_answers = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'leaderboard_entries'
        unique_together = ['quiz', 'participant']
        ordering = ['rank']
        indexes = [
            models.Index(fields=['quiz', 'rank']),
            models.Index(fields=['-score', 'time_taken']),
        ]

    def __str__(self):
        return f"#{self.rank} {self.participant.full_name} — {self.score}pts"
