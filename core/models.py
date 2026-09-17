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
        ('PROHIBITED_PROCESS', 'Prohibited Application Detected'),
        ('VM_DETECTED', 'Virtual Machine Detected'),
        ('GESTURE_SWIPE', 'Multi-Finger Gesture / App Switch Attempt'),
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


class AuditLog(models.Model):
    """
    Immutable, append-only security audit log for administrative,
    operational, and destructive actions across the platform.
    """
    ACTION_CHOICES = [
        ('QUIZ_CREATE', 'Create Quiz'),
        ('QUIZ_UPDATE', 'Update Quiz'),
        ('QUIZ_DELETE', 'Delete Quiz'),
        ('QUIZ_START', 'Start Quiz'),
        ('QUIZ_STOP', 'Stop Quiz'),
        ('QUIZ_PAUSE', 'Pause Quiz'),
        ('QUIZ_RESUME', 'Resume Quiz'),
        ('TIMER_EXTEND', 'Extend Quiz Timer'),
        ('QUESTION_CREATE', 'Create Question'),
        ('QUESTION_UPDATE', 'Update Question'),
        ('QUESTION_DELETE', 'Delete Question'),
        ('QUESTIONS_IMPORTED', 'Import Questions File'),
        ('PARTICIPANT_KICK', 'Kick Participant from Quiz'),
        ('PARTICIPANT_DELETE', 'Delete Participant Account'),
        ('ANNOUNCEMENT_BROADCAST', 'Broadcast Announcement'),
        ('RESULTS_EXPORT', 'Export Results'),
        ('VIEW_SUBMISSION', 'View Participant Submission'),
        ('OTHER', 'Other Administrative Action'),
    ]

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs'
    )
    actor_email = models.EmailField(blank=True, default='')
    action = models.CharField(max_length=50, choices=ACTION_CHOICES, db_index=True)
    target_model = models.CharField(max_length=50, blank=True, default='', db_index=True)
    target_id = models.CharField(max_length=50, blank=True, default='', db_index=True)
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'audit_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['action', '-created_at']),
            models.Index(fields=['target_model', 'target_id']),
            models.Index(fields=['actor_email', '-created_at']),
        ]

    def __str__(self):
        return f"[{self.created_at:%Y-%m-%d %H:%M:%S}] {self.actor_email or 'SYSTEM'} - {self.action} on {self.target_model}:{self.target_id}"

    def save(self, *args, **kwargs):
        """Strict append-only immutability guard: updates to existing rows are forbidden."""
        if self.pk and not kwargs.get('force_insert', False):
            if AuditLog.objects.filter(pk=self.pk).exists():
                raise PermissionError("AuditLog records are strictly immutable and cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Prevent deletion of audit records to maintain forensic integrity."""
        raise PermissionError("AuditLog records are append-only and cannot be deleted.")
