"""
Core models: base classes and violation logging.
"""
from django.db import models
from django.conf import settings


class TimeStampedModel(models.Model):
    """Abstract base model with created/updated timestamps."""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ViolationLog(TimeStampedModel):
    """Records anti-cheat violations during quizzes."""

    VIOLATION_TYPES = [
        ('TAB_SWITCH', 'Tab Switch'),
        ('WINDOW_BLUR', 'Window Blur'),
        ('FULLSCREEN_EXIT', 'Fullscreen Exit'),
        ('MULTIPLE_TABS', 'Multiple Tabs'),
        ('REFRESH', 'Page Refresh'),
        ('COPY', 'Copy Attempt'),
        ('PASTE', 'Paste Attempt'),
        ('RIGHT_CLICK', 'Right Click'),
        ('DEVTOOLS', 'DevTools Shortcut'),
        ('EXTENSION_DETECTED', 'Browser Extension Detected'),
        ('MOUSE_LEAVE', 'Mouse Left Window'),
        ('KEY_VIOLATION', 'Ctrl/Shift/Alt Key Violation'),
        ('OTHER', 'Other'),
    ]

    participant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='violations'
    )
    quiz = models.ForeignKey(
        'quiz.Quiz',
        on_delete=models.CASCADE,
        related_name='violations'
    )
    violation_type = models.CharField(max_length=30, choices=VIOLATION_TYPES)
    details = models.TextField(blank=True, default='')
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = 'violation_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['participant', 'quiz']),
            models.Index(fields=['violation_type']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"{self.participant.full_name} - {self.violation_type} ({self.created_at})"
