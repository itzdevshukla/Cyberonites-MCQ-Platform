"""
Participant model extending Django's AbstractUser.
Handles custom fields and single-session enforcement.
"""
from django.contrib.auth.models import AbstractUser
from django.db import models


class Participant(AbstractUser):
    """
    Custom user model for quiz participants.
    Uses email as the display identifier. Supports single active session.
    """
    full_name = models.CharField(max_length=200, help_text="Full name of the participant")
    email = models.EmailField(unique=True, help_text="Unique email address")
    college = models.CharField(max_length=300, help_text="College or institution name")
    session_key = models.CharField(
        max_length=100, blank=True, null=True,
        help_text="Current active session key for single-session enforcement"
    )

    class Meta:
        db_table = 'participants'
        ordering = ['full_name']
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['college']),
        ]

    def __str__(self):
        return f"{self.full_name} ({self.college})"

    def update_session(self, session_key):
        """Update the stored session key (kills previous session)."""
        self.session_key = session_key
        self.save(update_fields=['session_key'])

    def is_session_valid(self, current_session_key):
        """Check if the given session matches the active session."""
        return self.session_key == current_session_key
