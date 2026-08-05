"""
Admin dashboard and participant result views.
"""
import json
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_protect
from django.utils import timezone
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from accounts.decorators import admin_required, participant_required
from accounts.models import Participant
from quiz.models import Quiz, Question, Option, QuizParticipation, Answer, Announcement
from quiz.services import TimerService, ScoreCalculator
from leaderboard.services import LeaderboardService
from core.models import ViolationLog
from core.utils import calculate_percentile
from .exports import CSVExporter, ExcelExporter, PDFExporter

logger = logging.getLogger('quiz')


# ============================================================
# Admin Dashboard Views
# ============================================================

@admin_required
def admin_dashboard(request):
    """Admin home — overview stats."""
    quizzes = Quiz.objects.all()
    active_quiz = quizzes.filter(status='ACTIVE').first()
    total_participants = Participant.objects.filter(is_staff=False).count()

    active_participants = 0
    if active_quiz:
        active_participants = QuizParticipation.objects.filter(
            quiz=active_quiz, is_submitted=False
        ).count()

    context = {
        'quizzes': quizzes[:10],
        'active_quiz': active_quiz,
        'total_quizzes': quizzes.count(),
        'total_participants': total_participants,
        'active_participants': active_participants,
        'total_violations': ViolationLog.objects.count(),
    }
    return render(request, 'dashboard/admin/dashboard.html', context)


@admin_required
def quiz_list(request):
    """List all quizzes."""
    quizzes = Quiz.objects.all().order_by('-created_at')
    return render(request, 'dashboard/admin/quiz_list.html', {'quizzes': quizzes})


@admin_required
@require_http_methods(["GET", "POST"])
def quiz_create(request):
    """Create a new quiz."""
    if request.method == 'POST':
        quiz = Quiz.objects.create(
            title=request.POST.get('title', 'Untitled Quiz'),
            description=request.POST.get('description', ''),
            duration_minutes=int(request.POST.get('duration_minutes', 30)),
            randomize_questions=request.POST.get('randomize_questions') == 'on',
            randomize_options=request.POST.get('randomize_options') == 'on',
            allow_back_navigation=request.POST.get('allow_back_navigation') == 'on',
            max_violations=int(request.POST.get('max_violations', 3)),
            access_code=request.POST.get('access_code', '').strip(),
            created_by=request.user,
        )
        messages.success(request, f"Quiz '{quiz.title}' created successfully!")
        return redirect('dashboard:question_list', quiz_id=quiz.id)
    return render(request, 'dashboard/admin/quiz_form.html', {'quiz': None})


@admin_required
@require_http_methods(["GET", "POST"])
def quiz_edit(request, quiz_id):
    """Edit an existing quiz."""
    quiz = get_object_or_404(Quiz, id=quiz_id)
    if request.method == 'POST':
        quiz.title = request.POST.get('title', quiz.title)
        quiz.description = request.POST.get('description', quiz.description)
        quiz.duration_minutes = int(request.POST.get('duration_minutes', quiz.duration_minutes))
        quiz.randomize_questions = request.POST.get('randomize_questions') == 'on'
        quiz.randomize_options = request.POST.get('randomize_options') == 'on'
        quiz.allow_back_navigation = request.POST.get('allow_back_navigation') == 'on'
        quiz.max_violations = int(request.POST.get('max_violations', quiz.max_violations))
        quiz.access_code = request.POST.get('access_code', '').strip()
        quiz.save()
        messages.success(request, f"Quiz '{quiz.title}' updated!")
        return redirect('dashboard:quiz_list')
    return render(request, 'dashboard/admin/quiz_form.html', {'quiz': quiz})


@admin_required
@require_POST
def quiz_delete(request, quiz_id):
    """Delete a quiz safely with error handling."""
    quiz = get_object_or_404(Quiz, id=quiz_id)
    title = quiz.title
    try:
        quiz.delete()
        messages.success(request, f"Quiz '{title}' deleted successfully.")
    except Exception as e:
        logger.error(f"Failed to delete quiz '{title}': {e}")
        messages.error(request, f"Could not delete quiz '{title}': {str(e)}")

    return redirect('dashboard:quiz_list')



@admin_required
@require_POST
@csrf_protect
def quiz_control(request, quiz_id):
    """Control quiz state: start, stop, pause, resume, extend."""
    quiz = get_object_or_404(Quiz, id=quiz_id)
    action = request.POST.get('action', '')
    channel_layer = get_channel_layer()

    if action == 'start':
        TimerService.start_quiz(quiz)
        async_to_sync(channel_layer.group_send)(
            f'quiz_{quiz.id}',
            {
                'type': 'quiz_state_change',
                'status': 'ACTIVE',
                'remaining_seconds': TimerService.get_remaining_seconds(quiz),
                'message': 'Quiz has started! Good luck!',
            }
        )
        messages.success(request, "Quiz started!")

    elif action == 'stop':
        # Auto-submit all pending participants
        pending = QuizParticipation.objects.filter(quiz=quiz, is_submitted=False)
        for p in pending:
            ScoreCalculator.calculate(p)
            p.is_submitted = True
            p.finished_at = timezone.now()
            p.time_taken = (p.finished_at - p.started_at).total_seconds()
            p.save(update_fields=['is_submitted', 'finished_at', 'time_taken'])

        TimerService.stop_quiz(quiz)
        async_to_sync(channel_layer.group_send)(
            f'quiz_{quiz.id}',
            {
                'type': 'quiz_state_change',
                'status': 'COMPLETED',
                'remaining_seconds': 0,
                'message': 'Quiz has ended!',
            }
        )
        # Recalculate leaderboard
        LeaderboardService.recalculate_ranks(quiz)
        messages.success(request, "Quiz stopped and all pending submissions processed!")

    elif action == 'pause':
        remaining = TimerService.get_remaining_seconds(quiz)
        TimerService.pause_quiz(quiz)
        async_to_sync(channel_layer.group_send)(
            f'quiz_{quiz.id}',
            {
                'type': 'quiz_state_change',
                'status': 'PAUSED',
                'remaining_seconds': remaining,
                'message': 'Quiz has been paused by the admin.',
            }
        )
        messages.info(request, f"Quiz paused with {remaining}s remaining.")

    elif action == 'resume':
        remaining = int(request.POST.get('remaining_seconds', 0))
        TimerService.resume_quiz(quiz, remaining)
        async_to_sync(channel_layer.group_send)(
            f'quiz_{quiz.id}',
            {
                'type': 'quiz_state_change',
                'status': 'ACTIVE',
                'remaining_seconds': TimerService.get_remaining_seconds(quiz),
                'message': 'Quiz has been resumed!',
            }
        )
        messages.success(request, "Quiz resumed!")

    elif action == 'extend':
        extra = int(request.POST.get('extra_minutes', 5))
        TimerService.extend_timer(quiz, extra)
        async_to_sync(channel_layer.group_send)(
            f'quiz_{quiz.id}',
            {
                'type': 'timer_extended',
                'remaining_seconds': TimerService.get_remaining_seconds(quiz),
                'extra_minutes': extra,
            }
        )
        messages.success(request, f"Timer extended by {extra} minutes!")

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'status': quiz.status,
            'remaining_seconds': TimerService.get_remaining_seconds(quiz),
        })

    return redirect('dashboard:quiz_control_page', quiz_id=quiz.id)


@admin_required
def quiz_control_page(request, quiz_id):
    """Quiz control panel page with inline tabs."""
    quiz = get_object_or_404(Quiz, id=quiz_id)
    remaining = TimerService.get_remaining_seconds(quiz)
    participations = QuizParticipation.objects.filter(
        quiz=quiz
    ).select_related('participant').order_by('-score')
    questions = quiz.questions.prefetch_related('options').all()
    violations = ViolationLog.objects.filter(
        quiz=quiz
    ).select_related('participant').order_by('-created_at')

    context = {
        'quiz': quiz,
        'remaining_seconds': remaining,
        'total_participants': participations.count(),
        'submitted_count': participations.filter(is_submitted=True).count(),
        'active_count': participations.filter(is_submitted=False).count(),
        'questions': questions,
        'participations': participations,
        'violations': violations,
    }
    return render(request, 'dashboard/admin/quiz_control.html', context)



# ============================================================
# Question Management
# ============================================================

@admin_required
def question_list(request, quiz_id):
    """List all questions for a quiz."""
    quiz = get_object_or_404(Quiz, id=quiz_id)
    questions = quiz.questions.prefetch_related('options').all()
    return render(request, 'dashboard/admin/question_list.html', {
        'quiz': quiz,
        'questions': questions,
    })


@admin_required
@require_http_methods(["GET", "POST"])
def question_create(request, quiz_id):
    """Add a single question manually."""
    quiz = get_object_or_404(Quiz, id=quiz_id)

    if request.method == 'POST':
        question = Question.objects.create(
            quiz=quiz,
            text=request.POST.get('text', ''),
            topic=request.POST.get('topic', 'General'),
            difficulty=request.POST.get('difficulty', 'MEDIUM'),
            description=request.POST.get('description', ''),
            order=quiz.questions.count() + 1,
            marks=int(request.POST.get('marks', 1)),
            negative_marks=float(request.POST.get('negative_marks', 0)),
        )

        correct_option = request.POST.get('correct_option', 'A')
        for label in ['A', 'B', 'C', 'D']:
            Option.objects.create(
                question=question,
                label=label,
                text=request.POST.get(f'option_{label.lower()}', ''),
                is_correct=(label == correct_option),
            )

        quiz.recalculate_total_marks()
        messages.success(request, "Question added!")
        return redirect('dashboard:question_list', quiz_id=quiz.id)

    return render(request, 'dashboard/admin/question_form.html', {
        'quiz': quiz,
        'question': None,
    })


@admin_required
@require_http_methods(["GET", "POST"])
def question_edit(request, quiz_id, question_id):
    """Edit a question."""
    quiz = get_object_or_404(Quiz, id=quiz_id)
    question = get_object_or_404(Question, id=question_id, quiz=quiz)

    if request.method == 'POST':
        question.text = request.POST.get('text', question.text)
        question.topic = request.POST.get('topic', question.topic)
        question.difficulty = request.POST.get('difficulty', question.difficulty)
        question.description = request.POST.get('description', question.description)
        question.marks = int(request.POST.get('marks', question.marks))
        question.negative_marks = float(request.POST.get('negative_marks', question.negative_marks))
        question.save()

        correct_option = request.POST.get('correct_option', 'A')
        for label in ['A', 'B', 'C', 'D']:
            option, _ = Option.objects.get_or_create(
                question=question, label=label,
                defaults={'text': ''}
            )
            option.text = request.POST.get(f'option_{label.lower()}', option.text)
            option.is_correct = (label == correct_option)
            option.save()

        quiz.recalculate_total_marks()
        messages.success(request, "Question updated!")
        return redirect('dashboard:question_list', quiz_id=quiz.id)

    options = {opt.label: opt for opt in question.options.all()}
    return render(request, 'dashboard/admin/question_form.html', {
        'quiz': quiz,
        'question': question,
        'options': options,
    })


@admin_required
@require_POST
def question_delete(request, quiz_id, question_id):
    """Delete a question safely."""
    quiz = get_object_or_404(Quiz, id=quiz_id)
    question = get_object_or_404(Question, id=question_id, quiz=quiz)
    try:
        question.delete()
        quiz.recalculate_total_marks()
        messages.success(request, "Question deleted successfully.")
    except Exception as e:
        logger.error(f"Failed to delete question {question_id}: {e}")
        messages.error(request, f"Could not delete question: {str(e)}")

    next_url = request.META.get('HTTP_REFERER')
    if next_url:
        return redirect(next_url)
    return redirect('dashboard:question_list', quiz_id=quiz.id)


# ============================================================
# Participants & Violations
# ============================================================

@admin_required
def participant_list(request, quiz_id):
    """View participants for a quiz."""
    quiz = get_object_or_404(Quiz, id=quiz_id)
    participations = QuizParticipation.objects.filter(
        quiz=quiz
    ).select_related('participant').order_by('-score')

    return render(request, 'dashboard/admin/participants.html', {
        'quiz': quiz,
        'participations': participations,
    })


@admin_required
@require_POST
def quiz_kick_participant(request, quiz_id, participant_id):
    """Remove a participant from an active quiz and broadcast kick signal."""
    quiz = get_object_or_404(Quiz, id=quiz_id)
    participant = get_object_or_404(Participant, id=participant_id)

    try:
        participation = QuizParticipation.objects.filter(quiz=quiz, participant=participant).first()
        if participation:
            participation.delete()

        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'quiz_{quiz.id}',
            {
                'type': 'quiz_state_change',
                'status': 'KICKED',
                'participant_id': participant.id,
                'message': 'You have been removed from this quiz by the administrator.',
            }
        )

        messages.success(request, f"Participant '{participant.full_name}' removed from quiz '{quiz.title}'.")
    except Exception as e:
        logger.error(f"Failed to kick participant {participant_id}: {e}")
        messages.error(request, f"Could not remove participant: {str(e)}")

    next_url = request.META.get('HTTP_REFERER')
    if next_url:
        return redirect(next_url)
    return redirect('dashboard:participant_list', quiz_id=quiz.id)


@admin_required
@require_POST
def participant_delete(request, participant_id):
    """Permanently delete a participant account from the platform."""
    try:
        participant = get_object_or_404(Participant, id=participant_id, is_staff=False)
        name = participant.full_name
        email = participant.email
        participant.delete()
        messages.success(request, f"Participant '{name}' ({email}) permanently removed from platform.")
    except Exception as e:
        logger.error(f"Failed to delete participant {participant_id}: {e}")
        messages.error(request, f"Could not remove participant: {str(e)}")

    next_url = request.META.get('HTTP_REFERER')
    if next_url:
        return redirect(next_url)
    return redirect('dashboard:admin_dashboard')



@admin_required
def violation_list(request, quiz_id):
    """View anti-cheat violation logs."""
    quiz = get_object_or_404(Quiz, id=quiz_id)
    violations = ViolationLog.objects.filter(
        quiz=quiz
    ).select_related('participant').order_by('-created_at')

    return render(request, 'dashboard/admin/violations.html', {
        'quiz': quiz,
        'violations': violations,
    })



# ============================================================
# Announcements
# ============================================================

@admin_required
@require_POST
@csrf_protect
def broadcast_announcement(request, quiz_id):
    """Broadcast an announcement to all quiz participants."""
    quiz = get_object_or_404(Quiz, id=quiz_id)
    message_text = request.POST.get('message', '').strip()

    if not message_text:
        return JsonResponse({'error': 'Message cannot be empty.'}, status=400)

    announcement = Announcement.objects.create(
        quiz=quiz,
        message=message_text,
        created_by=request.user,
    )

    # Broadcast via WebSocket
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f'quiz_{quiz.id}',
        {
            'type': 'quiz_announcement',
            'message': message_text,
            'timestamp': announcement.created_at.isoformat(),
        }
    )

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'status': 'sent', 'message': message_text})

    messages.success(request, "Announcement broadcast!")
    return redirect('dashboard:quiz_control_page', quiz_id=quiz.id)


# ============================================================
# Exports
# ============================================================

@admin_required
def export_results(request, quiz_id):
    """Export results as CSV, Excel, or PDF."""
    quiz = get_object_or_404(Quiz, id=quiz_id)
    format_type = request.GET.get('format', 'csv')
    entries = LeaderboardService.get_leaderboard(quiz, limit=500)

    if format_type == 'excel':
        return ExcelExporter.export(quiz, entries)
    elif format_type == 'pdf':
        return PDFExporter.export(quiz, entries)
    else:
        return CSVExporter.export(quiz, entries)


# ============================================================
# Participant Result Views
# ============================================================

@participant_required
def result_page(request, quiz_id):
    """Participant result dashboard."""
    quiz = Quiz.objects.filter(id=quiz_id).first()
    if not quiz:
        messages.error(request, "Quiz not found or has been removed.")
        return redirect('quiz:lobby')

    participation = QuizParticipation.objects.filter(
        quiz=quiz, participant=request.user
    ).first()

    if not participation:
        messages.error(request, "No participation record found for this quiz or it was removed by admin.")
        return redirect('quiz:lobby')

    if not participation.is_submitted:
        return redirect('quiz:take_quiz', quiz_id=quiz.id)


    # Get detailed results
    answers = Answer.objects.filter(
        participation=participation
    ).select_related('question', 'selected_option').order_by('question__order')

    total = len(participation.question_order)
    correct = answers.filter(is_correct=True).count()
    wrong = answers.filter(is_correct=False, selected_option__isnull=False).count()
    skipped = total - answers.filter(selected_option__isnull=False).count()
    accuracy = round((correct / total * 100), 1) if total > 0 else 0

    # Get rank info
    rank_info = LeaderboardService.get_participant_rank(quiz, request.user)
    percentile = 0
    if rank_info:
        percentile = calculate_percentile(rank_info['rank'], rank_info['total_participants'])

    context = {
        'quiz': quiz,
        'participation': participation,
        'answers': answers,
        'correct': correct,
        'wrong': wrong,
        'skipped': skipped,
        'accuracy': accuracy,
        'total': total,
        'rank_info': rank_info,
        'percentile': percentile,
    }
    return render(request, 'dashboard/result/result.html', context)


@admin_required
def upload_questions_redirect(request, quiz_id):
    """Redirect to imports upload view."""
    from imports.views import upload_questions
    return upload_questions(request, quiz_id)
