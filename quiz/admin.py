from django.contrib import admin
from .models import Quiz, Question, Option, QuizParticipation, Answer, Announcement


class OptionInline(admin.TabularInline):
    model = Option
    extra = 4


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ('title', 'status', 'duration_minutes', 'question_count', 'created_at')
    list_filter = ('status',)


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('text', 'quiz', 'topic', 'difficulty', 'marks')
    list_filter = ('quiz', 'difficulty', 'topic')
    inlines = [OptionInline]


@admin.register(QuizParticipation)
class ParticipationAdmin(admin.ModelAdmin):
    list_display = ('participant', 'quiz', 'score', 'is_submitted', 'violation_count')
    list_filter = ('quiz', 'is_submitted')
