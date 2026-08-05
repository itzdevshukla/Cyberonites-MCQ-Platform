"""
Quiz engine models: Quiz, Question, Option, QuizParticipation, Answer, Announcement.
"""
from django.db import models
from django.conf import settings
from core.models import TimeStampedModel


class Quiz(TimeStampedModel):
    """Represents a quiz event."""

    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('ACTIVE', 'Active'),
        ('PAUSED', 'Paused'),
        ('COMPLETED', 'Completed'),
    ]

    title = models.CharField(max_length=300)
    description = models.TextField(blank=True, default='')
    duration_minutes = models.PositiveIntegerField(default=30, help_text="Quiz duration in minutes")
    total_marks = models.PositiveIntegerField(default=0, help_text="Auto-calculated from questions")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, related_name='created_quizzes'
    )

    # Randomization settings
    randomize_questions = models.BooleanField(default=True, help_text="Shuffle question order per participant")
    randomize_options = models.BooleanField(default=True, help_text="Shuffle option order per question per participant")

    # Navigation settings
    allow_back_navigation = models.BooleanField(default=True, help_text="Allow participants to navigate back to previous questions.")

    # Anti-cheat settings
    max_violations = models.PositiveIntegerField(default=3, help_text="Auto-submit after this many violations (0 = disabled)")

    # Access security
    access_code = models.CharField(max_length=50, blank=True, default='', help_text="Optional access code required for participants to enter quiz")


    class Meta:
        db_table = 'quizzes'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"{self.title} ({self.status})"

    @property
    def question_count(self):
        return self.questions.count()

    def recalculate_total_marks(self):
        """Recalculate total marks from all questions."""
        self.total_marks = self.questions.aggregate(
            total=models.Sum('marks')
        )['total'] or 0
        self.save(update_fields=['total_marks'])


class Question(TimeStampedModel):
    """Individual quiz question."""

    DIFFICULTY_CHOICES = [
        ('EASY', 'Easy'),
        ('MEDIUM', 'Medium'),
        ('HARD', 'Hard'),
    ]

    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='questions')
    text = models.TextField(help_text="Question text")
    topic = models.CharField(max_length=200, blank=True, default='General')
    difficulty = models.CharField(max_length=10, choices=DIFFICULTY_CHOICES, default='MEDIUM')
    description = models.TextField(blank=True, default='', help_text="Explanation shown after quiz")
    order = models.PositiveIntegerField(default=0)
    marks = models.PositiveIntegerField(default=1)
    negative_marks = models.FloatField(default=0, help_text="Marks deducted for wrong answer")

    class Meta:
        db_table = 'questions'
        ordering = ['order']
        indexes = [
            models.Index(fields=['quiz', 'order']),
            models.Index(fields=['topic']),
            models.Index(fields=['difficulty']),
        ]

    def __str__(self):
        return f"Q{self.order}: {self.text[:60]}..."

    @property
    def correct_option(self):
        return self.options.filter(is_correct=True).first()


class Option(models.Model):
    """Answer option for a question."""

    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='options')
    label = models.CharField(max_length=5, help_text="A, B, C, D")
    text = models.TextField(help_text="Option text")
    is_correct = models.BooleanField(default=False)

    class Meta:
        db_table = 'options'
        ordering = ['label']
        indexes = [
            models.Index(fields=['question']),
        ]

    def __str__(self):
        marker = " ✓" if self.is_correct else ""
        return f"{self.label}) {self.text[:40]}{marker}"


class QuizParticipation(TimeStampedModel):
    """
    Tracks a participant's attempt at a quiz.
    Stores randomized question/option orders per participant.
    """

    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='participations')
    participant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='quiz_participations'
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    is_submitted = models.BooleanField(default=False)
    time_taken = models.FloatField(null=True, blank=True, help_text="Time taken in seconds")
    score = models.FloatField(default=0)
    violation_count = models.PositiveIntegerField(default=0)

    # Randomized orders stored as JSON
    # question_order: [q_id1, q_id2, ...] — shuffled question IDs
    question_order = models.JSONField(default=list, help_text="Shuffled question ID order")
    # option_orders: {q_id: [opt_id1, opt_id2, ...]} — shuffled option IDs per question
    option_orders = models.JSONField(default=dict, help_text="Shuffled option orders per question")

    class Meta:
        db_table = 'quiz_participations'
        unique_together = ['quiz', 'participant']
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['quiz', 'participant']),
            models.Index(fields=['is_submitted']),
            models.Index(fields=['-score', 'time_taken']),
        ]

    def __str__(self):
        return f"{self.participant.full_name} - {self.quiz.title}"


class Answer(models.Model):
    """A participant's answer to a specific question."""

    participation = models.ForeignKey(
        QuizParticipation, on_delete=models.CASCADE, related_name='answers'
    )
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='answers')
    selected_option = models.ForeignKey(
        Option, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='selections'
    )
    is_correct = models.BooleanField(default=False)
    is_marked_for_review = models.BooleanField(default=False)
    answered_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'answers'
        unique_together = ['participation', 'question']
        indexes = [
            models.Index(fields=['participation', 'question']),
        ]

    def __str__(self):
        status = "✓" if self.is_correct else "✗" if self.selected_option else "—"
        return f"{status} Q{self.question.order}"


class Announcement(TimeStampedModel):
    """Admin broadcast announcement during a quiz."""

    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='announcements')
    message = models.TextField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, related_name='announcements'
    )

    class Meta:
        db_table = 'announcements'
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.created_at}] {self.message[:50]}..."
