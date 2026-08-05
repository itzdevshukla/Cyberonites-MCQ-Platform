"""
Models for tracking question uploads.
"""
from django.db import models
from django.conf import settings
from core.models import TimeStampedModel


class QuestionUpload(TimeStampedModel):
    """Tracks DOCX question upload history."""

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SUCCESS', 'Success'),
        ('PARTIAL', 'Partial Success'),
        ('FAILED', 'Failed'),
    ]

    file = models.FileField(upload_to='uploads/questions/')
    quiz = models.ForeignKey('quiz.Quiz', on_delete=models.CASCADE, related_name='uploads')
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    total_parsed = models.PositiveIntegerField(default=0)
    total_saved = models.PositiveIntegerField(default=0)
    error_log = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'question_uploads'
        ordering = ['-created_at']

    def __str__(self):
        return f"Upload #{self.id} - {self.status} ({self.total_saved}/{self.total_parsed})"
