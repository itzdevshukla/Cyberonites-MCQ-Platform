"""
Admin dashboard and participant result views.
"""
import json
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.db import transaction
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_protect
from django.utils import timezone
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from accounts.decorators import admin_required, participant_required
from accounts.models import Participant
from quiz.models import Quiz, Question, Option, QuizParticipation, Answer, Announcement
from quiz.services import TimerService, ScoreCalculator
from leaderboard.models import LeaderboardEntry
from leaderboard.services import LeaderboardService, RedisLeaderboardService
from core.models import ViolationLog, AuditLog
from core.audit import log_audit_event
from core.utils import calculate_percentile
from .exports import CSVExporter, ExcelExporter, PDFExporter

logger = logging.getLogger('quiz')


def _safe_int(val, default=0):
    """Safely parse integer with fallback default, preventing ValueError 500 crashes."""
    try:
        if val is None:
            return default
        str_val = str(val).strip()
        return int(str_val) if str_val else default
    except (ValueError, TypeError):
        return default


def _safe_float(val, default=0.0):
    """Safely parse float with fallback default, preventing ValueError 500 crashes."""
    try:
        if val is None:
            return default
        str_val = str(val).strip()
        return float(str_val) if str_val else default
    except (ValueError, TypeError):
        return default



# ============================================================
# Admin Dashboard Views
# ============================================================

@admin_required
def admin_dashboard(request):
    """Admin home — overview stats."""
    quizzes = []
    active_quiz = None
    total_quizzes = 0
    total_participants = 0
    active_participants = 0
    total_violations = 0
    total_audit_events = 0

    try:
        quizzes = list(Quiz.objects.all().order_by('-created_at')[:10])
        total_quizzes = Quiz.objects.count()
        active_quiz = Quiz.objects.filter(status='ACTIVE').first()
    except Exception as e:
        logger.error("Error querying quizzes in admin_dashboard: %s", e, exc_info=True)

    try:
        total_participants = Participant.objects.filter(is_staff=False).count()
    except Exception as e:
        logger.error("Error querying participants in admin_dashboard: %s", e, exc_info=True)

    if active_quiz:
        try:
            active_participants = QuizParticipation.objects.filter(
                quiz=active_quiz, is_submitted=False
            ).count()
        except Exception as e:
            logger.error("Error querying active participants in admin_dashboard: %s", e, exc_info=True)

    try:
        total_violations = ViolationLog.objects.count()
    except Exception as e:
        logger.error("Error querying violations in admin_dashboard: %s", e, exc_info=True)

    try:
        total_audit_events = AuditLog.objects.count()
    except Exception as e:
        logger.error("Error querying audit events in admin_dashboard: %s", e, exc_info=True)

    context = {
        'quizzes': quizzes,
        'active_quiz': active_quiz,
        'total_quizzes': total_quizzes,
        'total_participants': total_participants,
        'active_participants': active_participants,
        'total_violations': total_violations,
        'total_audit_events': total_audit_events,
    }
    try:
        return render(request, 'dashboard/admin/dashboard.html', context)
    except Exception as e:
        logger.error("Error rendering admin_dashboard template: %s", e, exc_info=True)
        return render(request, 'dashboard/admin/base_admin.html', context)


@admin_required
def quiz_list(request):
    """List all quizzes."""
    """List all quizzes."""
    try:
        quizzes = Quiz.objects.all().order_by('-created_at')
    except Exception as e:
        logger.error("Error in quiz_list: %s", e, exc_info=True)
        quizzes = []
    return render(request, 'dashboard/admin/quiz_list.html', {'quizzes': quizzes})


@admin_required
@require_http_methods(["GET", "POST"])
def quiz_create(request):
    """Create a new quiz with zero-downtime database column fallback."""
    if request.method == 'POST':
        try:
            create_kwargs = {
                'title': request.POST.get('title', 'Untitled Quiz').strip() or 'Untitled Quiz',
                'description': request.POST.get('description', '').strip(),
                'duration_minutes': _safe_int(request.POST.get('duration_minutes'), 30),
                'randomize_questions': request.POST.get('randomize_questions') == 'on',
                'randomize_options': request.POST.get('randomize_options') == 'on',
                'allow_back_navigation': request.POST.get('allow_back_navigation') == 'on',
                'enable_question_timer': request.POST.get('enable_question_timer') == 'on',
                'question_timer_seconds': _safe_int(request.POST.get('question_timer_seconds'), 20),
                'is_proctored': request.POST.get('is_proctored') == 'on',
                'max_violations': _safe_int(request.POST.get('max_violations'), 3),
                'access_code': request.POST.get('access_code', '').strip(),
                'created_by': request.user,
            }
            try:
                quiz = Quiz.objects.create(**create_kwargs)
            except Exception as db_err:
                err_str = str(db_err).lower()
                if 'enable_question_timer' in err_str or 'question_timer' in err_str:
                    logger.warning("Database column for question timer missing on Quiz table, creating with fallback: %s", db_err)
                    create_kwargs.pop('enable_question_timer', None)
                    create_kwargs.pop('question_timer_seconds', None)
                    quiz = Quiz.objects.create(**create_kwargs)
                else:
                    raise db_err

            log_audit_event(
                request=request,
                action='QUIZ_CREATE',
                target_model='Quiz',
                target_id=str(quiz.id),
                details={
                    'title': quiz.title,
                    'duration_minutes': quiz.duration_minutes,
                    'is_proctored': quiz.is_proctored,
                    'max_violations': quiz.max_violations
                }
            )
            messages.success(request, f"Quiz '{quiz.title}' created successfully!")
            return redirect('dashboard:question_list', quiz_id=quiz.id)
        except Exception as e:
            logger.error("Error creating quiz: %s", e, exc_info=True)
            messages.error(request, f"Error creating quiz: {e}. Please ensure migrations are applied ('python manage.py migrate').")
            return render(request, 'dashboard/admin/quiz_form.html', {'quiz': None})
    return render(request, 'dashboard/admin/quiz_form.html', {'quiz': None})


@admin_required
@require_http_methods(["GET", "POST"])
@csrf_protect
def quiz_edit(request, quiz_id):
    """Edit an existing quiz with change diff auditing and zero-downtime column fallback."""
    quiz = get_object_or_404(Quiz, id=quiz_id)
    if request.method == 'POST':
        try:
            old_values = {
                'title': quiz.title,
                'duration_minutes': quiz.duration_minutes,
                'is_proctored': quiz.is_proctored,
                'randomize_questions': quiz.randomize_questions,
                'randomize_options': quiz.randomize_options,
                'allow_back_navigation': quiz.allow_back_navigation,
                'max_violations': quiz.max_violations,
            }

            quiz.title = request.POST.get('title', quiz.title).strip()
            quiz.description = request.POST.get('description', quiz.description).strip()
            quiz.duration_minutes = _safe_int(request.POST.get('duration_minutes'), quiz.duration_minutes)
            quiz.randomize_questions = request.POST.get('randomize_questions') == 'on'
            quiz.randomize_options = request.POST.get('randomize_options') == 'on'
            quiz.allow_back_navigation = request.POST.get('allow_back_navigation') == 'on'
            quiz.is_proctored = request.POST.get('is_proctored') == 'on'
            quiz.max_violations = _safe_int(request.POST.get('max_violations'), quiz.max_violations)
            quiz.access_code = request.POST.get('access_code', '').strip()

            try:
                quiz.enable_question_timer = request.POST.get('enable_question_timer') == 'on'
                quiz.question_timer_seconds = _safe_int(request.POST.get('question_timer_seconds'), 20)
                quiz.save()
            except Exception as db_err:
                err_str = str(db_err).lower()
                if 'enable_question_timer' in err_str or 'question_timer' in err_str:
                    logger.warning("Database column for question timer missing on save, saving without timer fields: %s", db_err)
                    quiz.save(update_fields=[
                        'title', 'description', 'duration_minutes', 'randomize_questions',
                        'randomize_options', 'allow_back_navigation', 'is_proctored',
                        'max_violations', 'access_code', 'updated_at'
                    ])
                else:
                    raise db_err

            changed_fields = {}
            for field, old_val in old_values.items():
                new_val = getattr(quiz, field, None)
                if old_val != new_val:
                    changed_fields[field] = {'from': old_val, 'to': new_val}

            log_audit_event(
                request=request,
                action='QUIZ_UPDATE',
                target_model='Quiz',
                target_id=str(quiz.id),
                details={
                    'title': quiz.title,
                    'changed_fields': changed_fields,
                    'is_proctored': quiz.is_proctored,
                    'duration_minutes': quiz.duration_minutes
                }
            )
            messages.success(request, f"Quiz '{quiz.title}' updated!")
            return redirect('dashboard:quiz_list')
        except Exception as e:
            logger.error("Error editing quiz %s: %s", quiz_id, e, exc_info=True)
            messages.error(request, f"Error updating quiz: {e}")
            return render(request, 'dashboard/admin/quiz_form.html', {'quiz': quiz})
    return render(request, 'dashboard/admin/quiz_form.html', {'quiz': quiz})



@admin_required
@require_POST
@csrf_protect
def quiz_delete(request, quiz_id):
    """Delete a quiz safely with complete forensic cascade audit logging."""
    quiz = get_object_or_404(Quiz, id=quiz_id)
    title = quiz.title
    status = quiz.status
    questions_count = quiz.questions.count()
    participations_count = quiz.participations.count()
    leaderboard_count = quiz.leaderboard_entries.count()
    answers_count = Answer.objects.filter(participation__quiz=quiz).count()

    try:
        quiz.delete()
        RedisLeaderboardService.clear_quiz_cache(quiz_id)
        log_audit_event(
            request=request,
            action='QUIZ_DELETE',
            target_model='Quiz',
            target_id=str(quiz_id),
            details={
                'title': title,
                'status': status,
                'questions_count': questions_count,
                'participations_count': participations_count,
                'answers_count': answers_count,
                'leaderboard_count': leaderboard_count,
                'operator_username': request.user.username,
                'timestamp': timezone.now().isoformat()
            }
        )
        messages.success(request, f"Quiz '{title}' and associated records deleted successfully.")
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
        log_audit_event(
            request=request,
            action='QUIZ_START',
            target_model='Quiz',
            target_id=str(quiz.id),
            details={'title': quiz.title}
        )
        try:
            if channel_layer:
                async_to_sync(channel_layer.group_send)(
                    f'quiz_{quiz.id}',
                    {
                        'type': 'quiz_state_change',
                        'status': 'ACTIVE',
                        'remaining_seconds': TimerService.get_remaining_seconds(quiz),
                        'message': 'Quiz has started! Good luck!',
                    }
                )
        except Exception as e:
            logger.warning(f"Failed to broadcast quiz start: {e}")
        messages.success(request, "Quiz started!")

    elif action == 'stop':
        # Auto-submit all pending participants
        pending = QuizParticipation.objects.filter(quiz=quiz, is_submitted=False)
        pending_count = pending.count()
        for p in pending:
            p.transition_to('SUBMITTED', save=False)
            res = ScoreCalculator.calculate(p)
            p.score = res['score']
            p.transition_to('EVALUATED', save=False)
            p.finished_at = timezone.now()
            start_ts = p.started_at or p.finished_at
            p.time_taken = max(0.0, (p.finished_at - start_ts).total_seconds())
            p.save(update_fields=['status', 'is_submitted', 'score', 'finished_at', 'time_taken'])

        TimerService.stop_quiz(quiz)
        log_audit_event(
            request=request,
            action='QUIZ_STOP',
            target_model='Quiz',
            target_id=str(quiz.id),
            details={'title': quiz.title, 'auto_submitted_count': pending_count}
        )
        try:
            if channel_layer:
                async_to_sync(channel_layer.group_send)(
                    f'quiz_{quiz.id}',
                    {
                        'type': 'quiz_state_change',
                        'status': 'COMPLETED',
                        'remaining_seconds': 0,
                        'message': 'Quiz has ended!',
                    }
                )
        except Exception as e:
            logger.warning(f"Failed to broadcast quiz stop: {e}")
        # Recalculate leaderboard
        LeaderboardService.recalculate_ranks(quiz)
        messages.success(request, "Quiz stopped and all pending submissions processed!")

    elif action == 'pause':
        remaining = TimerService.get_remaining_seconds(quiz)
        TimerService.pause_quiz(quiz)
        log_audit_event(
            request=request,
            action='QUIZ_PAUSE',
            target_model='Quiz',
            target_id=str(quiz.id),
            details={'title': quiz.title, 'remaining_seconds': remaining}
        )
        try:
            if channel_layer:
                async_to_sync(channel_layer.group_send)(
                    f'quiz_{quiz.id}',
                    {
                        'type': 'quiz_state_change',
                        'status': 'PAUSED',
                        'remaining_seconds': remaining,
                        'message': 'Quiz has been paused by the admin.',
                    }
                )
        except Exception as e:
            logger.warning(f"Failed to broadcast quiz pause: {e}")
        messages.info(request, f"Quiz paused with {remaining}s remaining.")

    elif action == 'resume':
        remaining = _safe_int(request.POST.get('remaining_seconds'), 0)
        TimerService.resume_quiz(quiz, remaining)
        log_audit_event(
            request=request,
            action='QUIZ_RESUME',
            target_model='Quiz',
            target_id=str(quiz.id),
            details={'title': quiz.title, 'remaining_seconds': remaining}
        )
        try:
            if channel_layer:
                async_to_sync(channel_layer.group_send)(
                    f'quiz_{quiz.id}',
                    {
                        'type': 'quiz_state_change',
                        'status': 'ACTIVE',
                        'remaining_seconds': TimerService.get_remaining_seconds(quiz),
                        'message': 'Quiz has been resumed!',
                    }
                )
        except Exception as e:
            logger.warning(f"Failed to broadcast quiz resume: {e}")
        messages.success(request, "Quiz resumed!")

    elif action == 'extend':
        extra = _safe_int(request.POST.get('extra_minutes'), 5)
        TimerService.extend_timer(quiz, extra)
        log_audit_event(
            request=request,
            action='TIMER_EXTEND',
            target_model='Quiz',
            target_id=str(quiz.id),
            details={'title': quiz.title, 'extra_minutes': extra}
        )
        try:
            if channel_layer:
                async_to_sync(channel_layer.group_send)(
                    f'quiz_{quiz.id}',
                    {
                        'type': 'timer_extended',
                        'remaining_seconds': TimerService.get_remaining_seconds(quiz),
                        'extra_minutes': extra,
                    }
                )
        except Exception as e:
            logger.warning(f"Failed to broadcast timer extend: {e}")
        messages.success(request, f"Timer extended by {extra} minutes!")

    elif action == 'reopen':
        extra = _safe_int(request.POST.get('extra_minutes'), 15)
        reopen_participants = request.POST.get('reopen_participants') in ('true', 'on', '1')
        from datetime import timedelta
        now = timezone.now()
        quiz.status = 'ACTIVE'
        quiz.end_time = now + timedelta(minutes=extra)
        quiz.save(update_fields=['status', 'end_time'])

        reopened_count = 0
        if reopen_participants:
            for p in quiz.participations.all():
                p.status = 'IN_PROGRESS'
                p.is_submitted = False
                p.finished_at = None
                p.save(update_fields=['status', 'is_submitted', 'finished_at'])
                reopened_count += 1

        log_audit_event(
            request=request,
            action='QUIZ_RESUME',
            target_model='Quiz',
            target_id=str(quiz.id),
            details={'title': quiz.title, 'reopened': True, 'extra_minutes': extra, 'reopened_participants': reopened_count}
        )
        try:
            if channel_layer:
                async_to_sync(channel_layer.group_send)(
                    f'quiz_{quiz.id}',
                    {
                        'type': 'quiz_state_change',
                        'status': 'ACTIVE',
                        'remaining_seconds': extra * 60,
                        'message': f'Quiz has been reopened with {extra} additional minutes!',
                    }
                )
        except Exception as e:
            logger.warning(f"Failed to broadcast quiz reopen: {e}")
        messages.success(request, f"Quiz '{quiz.title}' reopened! Added {extra} minutes. ({reopened_count} attempts reopened to In Progress)")

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
    """Add a single question manually with zero-downtime column fallback."""
    quiz = get_object_or_404(Quiz, id=quiz_id)

    if request.method == 'POST':
        try:
            timer_raw = request.POST.get('timer_seconds', '').strip()
            timer_seconds = int(timer_raw) if timer_raw.isdigit() and int(timer_raw) > 0 else None

            q_kwargs = {
                'quiz': quiz,
                'text': request.POST.get('text', '').strip() or 'Untitled Question',
                'topic': request.POST.get('topic', 'General').strip() or 'General',
                'difficulty': request.POST.get('difficulty', 'MEDIUM'),
                'description': request.POST.get('description', '').strip(),
                'order': quiz.questions.count() + 1,
                'marks': _safe_int(request.POST.get('marks'), 1),
                'negative_marks': _safe_float(request.POST.get('negative_marks'), 0.0),
                'timer_seconds': timer_seconds,
            }

            try:
                question = Question.objects.create(**q_kwargs)
            except Exception as db_err:
                if 'timer_seconds' in str(db_err).lower():
                    logger.warning("timer_seconds column missing on Question table, creating without timer: %s", db_err)
                    q_kwargs.pop('timer_seconds', None)
                    question = Question.objects.create(**q_kwargs)
                else:
                    raise db_err

            correct_option = request.POST.get('correct_option', 'A')
            for label in ['A', 'B', 'C', 'D']:
                Option.objects.create(
                    question=question,
                    label=label,
                    text=request.POST.get(f'option_{label.lower()}', ''),
                    is_correct=(label == correct_option),
                )

            quiz.recalculate_total_marks()
            log_audit_event(
                request=request,
                action='QUESTION_CREATE',
                target_model='Question',
                target_id=str(question.id),
                details={
                    'quiz_id': quiz.id,
                    'quiz_title': quiz.title,
                    'text': question.text[:120],
                    'marks': question.marks,
                    'negative_marks': question.negative_marks
                }
            )
            messages.success(request, "Question added!")
            return redirect('dashboard:question_list', quiz_id=quiz.id)
        except Exception as e:
            logger.error("Error creating question for quiz %s: %s", quiz_id, e, exc_info=True)
            messages.error(request, f"Error adding question: {e}")
            return render(request, 'dashboard/admin/question_form.html', {
                'quiz': quiz,
                'question': None,
            })

    return render(request, 'dashboard/admin/question_form.html', {
        'quiz': quiz,
        'question': None,
    })


@admin_required
@require_http_methods(["GET", "POST"])
def question_edit(request, quiz_id, question_id):
    """Edit a question with zero-downtime column fallback."""
    quiz = get_object_or_404(Quiz, id=quiz_id)
    question = get_object_or_404(Question, id=question_id, quiz=quiz)

    if request.method == 'POST':
        try:
            question.text = request.POST.get('text', question.text).strip()
            question.topic = request.POST.get('topic', question.topic).strip()
            question.difficulty = request.POST.get('difficulty', question.difficulty)
            question.description = request.POST.get('description', question.description).strip()
            question.marks = _safe_int(request.POST.get('marks'), question.marks)
            question.negative_marks = _safe_float(request.POST.get('negative_marks'), question.negative_marks)
            timer_raw = request.POST.get('timer_seconds', '').strip()
            timer_seconds = int(timer_raw) if timer_raw.isdigit() and int(timer_raw) > 0 else None

            try:
                question.timer_seconds = timer_seconds
                question.save()
            except Exception as db_err:
                if 'timer_seconds' in str(db_err).lower():
                    logger.warning("timer_seconds column missing, saving without timer: %s", db_err)
                    question.save(update_fields=['text', 'topic', 'difficulty', 'description', 'marks', 'negative_marks', 'updated_at'])
                else:
                    raise db_err

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
            log_audit_event(
                request=request,
                action='QUESTION_UPDATE',
                target_model='Question',
                target_id=str(question.id),
                details={
                    'quiz_id': quiz.id,
                    'quiz_title': quiz.title,
                    'text': question.text[:120],
                    'marks': question.marks,
                    'negative_marks': question.negative_marks
                }
            )
            messages.success(request, "Question updated successfully!")
            return redirect('dashboard:question_list', quiz_id=quiz.id)
        except Exception as e:
            logger.error("Error editing question %s: %s", question_id, e, exc_info=True)
            messages.error(request, f"Error updating question: {e}")
            return render(request, 'dashboard/admin/question_form.html', {
                'quiz': quiz,
            })

    options = {opt.label: opt for opt in question.options.all()}

    return render(request, 'dashboard/admin/question_form.html', {
        'quiz': quiz,
        'question': question,
        'options': options,
    })


@admin_required
@require_POST
@csrf_protect
def question_delete(request, quiz_id, question_id):
    """Delete a question safely with full forensic audit metadata."""
    quiz = get_object_or_404(Quiz, id=quiz_id)
    question = get_object_or_404(Question, id=question_id, quiz=quiz)
    question_text = question.text[:150]
    marks = question.marks
    negative_marks = question.negative_marks
    options_count = question.options.count()

    try:
        question.delete()
        quiz.recalculate_total_marks()
        log_audit_event(
            request=request,
            action='QUESTION_DELETE',
            target_model='Question',
            target_id=str(question_id),
            details={
                'quiz_id': quiz.id,
                'quiz_title': quiz.title,
                'marks': marks,
                'negative_marks': negative_marks,
                'options_count': options_count,
                'text': question_text
            }
        )
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
def participant_submission_detail(request, quiz_id, participant_id):
    """
    Forensic submission inspector for administrators.
    Provides complete question-by-question analysis:
    - Candidate's selected option vs actual correct option
    - Marks awarded (+X), marks deducted (-Y), or zero (skipped)
    - Correct / Incorrect / Skipped status
    - Exact candidate question order & randomized option order
    - Time taken, score, anti-cheat violation events
    - Questions explanations and timestamps
    Strictly restricted to staff and audited via AuditLog.
    """
    quiz = get_object_or_404(Quiz, id=quiz_id)

    # Support lookup by either Participant User PK or QuizParticipation PK
    participation = (
        QuizParticipation.objects.filter(quiz=quiz, participant_id=participant_id).select_related('participant', 'quiz').first()
        or QuizParticipation.objects.filter(quiz=quiz, id=participant_id).select_related('participant', 'quiz').first()
    )
    if not participation:
        messages.error(request, "No submission or participation record found for this participant in this quiz.")
        return redirect('dashboard:participant_list', quiz_id=quiz.id)

    # Immutable security audit logging
    log_audit_event(
        request=request,
        action='VIEW_SUBMISSION',
        target_model='QuizParticipation',
        target_id=str(participation.id),
        details={
            'quiz_id': quiz.id,
            'quiz_title': quiz.title,
            'participant_id': participation.participant.id,
            'participant_name': participation.participant.full_name,
            'participant_email': participation.participant.email,
            'score': participation.score,
            'status': participation.status,
            'is_submitted': participation.is_submitted,
        }
    )

    # Fetch all questions for this quiz prefetching options
    questions_queryset = quiz.questions.prefetch_related('options').all()
    questions_map = {q.id: q for q in questions_queryset}

    # Respect candidate's randomized question sequence if present
    ordered_questions = []
    if participation.question_order and isinstance(participation.question_order, list):
        for q_id in participation.question_order:
            if q_id in questions_map:
                ordered_questions.append(questions_map[q_id])

    # Append any remaining questions (fallback)
    seen_ids = {q.id for q in ordered_questions}
    for q in questions_queryset.order_by('order'):
        if q.id not in seen_ids:
            ordered_questions.append(q)

    # Fetch all candidate answers
    answers = Answer.objects.filter(
        participation=participation
    ).select_related('selected_option', 'question')
    answers_map = {ans.question_id: ans for ans in answers}

    # Build question-level forensic details
    detailed_questions = []
    correct_count = 0
    wrong_count = 0
    skipped_count = 0
    total_questions = len(ordered_questions)
    option_orders_map = participation.option_orders or {}

    for idx, question in enumerate(ordered_questions, start=1):
        ans = answers_map.get(question.id)
        selected_option = ans.selected_option if ans else None
        is_marked_for_review = ans.is_marked_for_review if ans else False
        answered_at = ans.answered_at if ans else None

        # Determine question status and marks delta
        if selected_option is not None:
            if ans.is_correct:
                status = 'CORRECT'
                marks_awarded = question.marks
                correct_count += 1
            else:
                status = 'INCORRECT'
                marks_awarded = -question.negative_marks
                wrong_count += 1
        else:
            status = 'SKIPPED'
            marks_awarded = 0
            skipped_count += 1

        # Options processing
        options_list = list(question.options.all())
        custom_opt_order = option_orders_map.get(str(question.id))
        if custom_opt_order and isinstance(custom_opt_order, list):
            opt_map = {opt.id: opt for opt in options_list}
            ordered_opts = [opt_map[oid] for oid in custom_opt_order if oid in opt_map]
            for opt in options_list:
                if opt not in ordered_opts:
                    ordered_opts.append(opt)
            options_list = ordered_opts
        else:
            options_list.sort(key=lambda o: o.label)

        options_data = []
        for opt in options_list:
            is_selected = (selected_option is not None and opt.id == selected_option.id)
            options_data.append({
                'id': opt.id,
                'label': opt.label,
                'text': opt.text,
                'is_correct': opt.is_correct,
                'is_selected': is_selected,
            })

        detailed_questions.append({
            'index': idx,
            'question': question,
            'status': status,
            'marks_awarded': marks_awarded,
            'selected_option': selected_option,
            'is_marked_for_review': is_marked_for_review,
            'answered_at': answered_at,
            'options': options_data,
        })

    # Summary calculations
    attempted_count = correct_count + wrong_count
    accuracy = round((correct_count / attempted_count * 100), 1) if attempted_count > 0 else 0
    score_percentage = round((participation.score / quiz.total_marks * 100), 1) if quiz.total_marks > 0 else 0

    # Fetch candidate's anti-cheat violation events
    violations = ViolationLog.objects.filter(
        quiz=quiz,
        participant=participation.participant
    ).order_by('-created_at')

    # Get adjacent participants for rapid navigation
    all_participations = list(
        QuizParticipation.objects.filter(quiz=quiz)
        .select_related('participant')
        .order_by('-score', 'time_taken')
        .values_list('id', 'participant_id', 'participant__full_name')
    )
    prev_participant = None
    next_participant = None
    current_idx = None
    for i, (part_pk, u_pk, name) in enumerate(all_participations):
        if part_pk == participation.id:
            current_idx = i
            break

    if current_idx is not None:
        if current_idx > 0:
            prev_participant = {
                'id': all_participations[current_idx - 1][1],
                'name': all_participations[current_idx - 1][2]
            }
        if current_idx < len(all_participations) - 1:
            next_participant = {
                'id': all_participations[current_idx + 1][1],
                'name': all_participations[current_idx + 1][2]
            }

    context = {
        'quiz': quiz,
        'participation': participation,
        'participant': participation.participant,
        'detailed_questions': detailed_questions,
        'total_questions': total_questions,
        'attempted_count': attempted_count,
        'correct_count': correct_count,
        'wrong_count': wrong_count,
        'skipped_count': skipped_count,
        'accuracy': accuracy,
        'score_percentage': score_percentage,
        'violations': violations,
        'violation_count': violations.count(),
        'prev_participant': prev_participant,
        'next_participant': next_participant,
        'all_participations': [
            {'id': u_pk, 'name': name, 'is_current': (part_pk == participation.id)}
            for part_pk, u_pk, name in all_participations
        ],
    }
    return render(request, 'dashboard/admin/submission_detail.html', context)


@admin_required
@require_POST
@csrf_protect
def quiz_kick_participant(request, quiz_id, participant_id):
    """Remove a participant from an active quiz, clear their leaderboard entry, and broadcast kick signal."""
    quiz = get_object_or_404(Quiz, id=quiz_id)
    participant = get_object_or_404(Participant, id=participant_id)

    try:
        with transaction.atomic():
            participation = QuizParticipation.objects.select_for_update().filter(quiz=quiz, participant=participant).first()
            if participation:
                participation.delete()
            LeaderboardEntry.objects.filter(quiz=quiz, participant=participant).delete()
            LeaderboardService.recalculate_ranks(quiz)

        log_audit_event(
            request=request,
            action='PARTICIPANT_KICK',
            target_model='Participant',
            target_id=str(participant.id),
            details={
                'quiz_id': quiz.id,
                'quiz_title': quiz.title,
                'participant_name': participant.full_name,
                'participant_email': participant.email
            }
        )

        try:
            channel_layer = get_channel_layer()
            if channel_layer:
                async_to_sync(channel_layer.group_send)(
                    f'quiz_{quiz.id}',
                    {
                        'type': 'quiz_state_change',
                        'status': 'KICKED',
                        'participant_id': participant.id,
                        'message': 'You have been removed from this quiz by the administrator.',
                    }
                )
        except Exception as ws_err:
            logger.warning(f"Failed to broadcast kick notification: {ws_err}")

        messages.success(request, f"Participant '{participant.full_name}' removed from quiz '{quiz.title}'.")
    except Exception as e:
        logger.error(f"Failed to kick participant {participant_id}: {e}")
        messages.error(request, f"Could not remove participant: {str(e)}")

    next_url = request.META.get('HTTP_REFERER')
    if next_url:
        return redirect(next_url)
    return redirect('dashboard:quiz_control_page', quiz_id=quiz.id)


@admin_required
@require_POST
@csrf_protect
def participant_delete(request, participant_id):
    """Permanently delete a participant account and all their records from the platform."""
    participant = get_object_or_404(Participant, id=participant_id, is_staff=False)
    name = participant.full_name
    email = participant.email
    active_quiz_ids = list(participant.quiz_participations.values_list('quiz_id', flat=True))

    try:
        with transaction.atomic():
            participant.delete()

        try:
            channel_layer = get_channel_layer()
            if channel_layer:
                for q_id in active_quiz_ids:
                    async_to_sync(channel_layer.group_send)(
                        f'quiz_{q_id}',
                        {
                            'type': 'quiz_state_change',
                            'status': 'KICKED',
                            'participant_id': participant_id,
                            'message': 'Your account has been removed from the platform by the administrator.',
                        }
                    )
        except Exception as ws_err:
            logger.warning(f"Failed to broadcast account deletion signal: {ws_err}")

        log_audit_event(
            request=request,
            action='PARTICIPANT_DELETE',
            target_model='Participant',
            target_id=str(participant_id),
            details={
                'participant_name': name,
                'participant_email': email
            }
        )
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

    log_audit_event(
        request=request,
        action='ANNOUNCEMENT_BROADCAST',
        target_model='Announcement',
        target_id=str(announcement.id),
        details={
            'quiz_id': quiz.id,
            'quiz_title': quiz.title,
            'message': message_text[:250]
        }
    )

    # Broadcast via WebSocket safely
    try:
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f'quiz_{quiz.id}',
                {
                    'type': 'quiz_announcement',
                    'message': message_text,
                    'timestamp': announcement.created_at.isoformat(),
                }
            )
    except Exception as ws_err:
        logger.warning(f"Failed to broadcast announcement WebSocket: {ws_err}")

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'status': 'sent', 'message': message_text})

    messages.success(request, "Announcement broadcast!")
    return redirect('dashboard:quiz_control_page', quiz_id=quiz.id)


# ============================================================
# Exports & Audit Log Trail
# ============================================================

@admin_required
def export_results(request, quiz_id):
    """Export results as streaming CSV, Excel, or PDF with flat O(1) memory footprint."""
    quiz = get_object_or_404(Quiz, id=quiz_id)
    format_type = request.GET.get('format', 'csv')
    total_participants = quiz.leaderboard_entries.count()
    entries_iterator = LeaderboardService.get_leaderboard_iterator(quiz, chunk_size=500)

    log_audit_event(
        request=request,
        action='RESULTS_EXPORT',
        target_model='Quiz',
        target_id=str(quiz.id),
        details={
            'quiz_title': quiz.title,
            'format': format_type,
            'participant_count': total_participants
        }
    )

    if format_type == 'excel':
        return ExcelExporter.export(quiz, entries_iterator)
    elif format_type == 'pdf':
        return PDFExporter.export(quiz, entries_iterator)
    else:
        return CSVExporter.export(quiz, entries_iterator)



@admin_required
def audit_log_list(request):
    """View, search, and filter persistent immutable audit trail."""
    from django.core.paginator import Paginator
    from django.db.models import Q

    action_filter = request.GET.get('action', '').strip()
    search_query = request.GET.get('q', '').strip()
    page_number = request.GET.get('page', 1)

    logs = AuditLog.objects.all().order_by('-created_at')

    if action_filter:
        logs = logs.filter(action=action_filter)

    if search_query:
        logs = logs.filter(
            Q(actor_email__icontains=search_query) |
            Q(target_model__icontains=search_query) |
            Q(target_id__icontains=search_query) |
            Q(ip_address__icontains=search_query)
        )

    paginator = Paginator(logs, 50)
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'action_choices': AuditLog.ACTION_CHOICES,
        'selected_action': action_filter,
        'search_query': search_query,
        'total_logs': logs.count(),
    }
    return render(request, 'dashboard/admin/audit_logs.html', context)


# ============================================================
# Participant Result Views
# ============================================================

@participant_required
def result_page(request, quiz_id):
    """Participant result dashboard with defensive error handling."""
    try:
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

        total = len(participation.question_order or []) or quiz.questions.count()
        correct = answers.filter(is_correct=True).count()
        wrong = answers.filter(is_correct=False, selected_option__isnull=False).count()
        attempted = answers.filter(selected_option__isnull=False).count()
        skipped = max(0, total - attempted)
        accuracy = round((correct / total * 100), 1) if total > 0 else 0

        # Get rank info
        rank_info = None
        percentile = 0
        try:
            rank_info = LeaderboardService.get_participant_rank(quiz, request.user)
            if rank_info:
                percentile = calculate_percentile(rank_info['rank'], rank_info['total_participants'])
        except Exception as e:
            logger.warning("Could not calculate participant rank: %s", e)

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
    except Exception as e:
        logger.error("Error loading result_page for user %s, quiz %s: %s", getattr(request.user, 'email', 'anonymous'), quiz_id, e, exc_info=True)
        messages.error(request, "Your exam was submitted successfully! (An error occurred loading the detailed scorecard).")
        return redirect('quiz:lobby')



@admin_required
def upload_questions_redirect(request, quiz_id):
    """Redirect to imports upload view."""
    from imports.views import upload_questions
    return upload_questions(request, quiz_id)


@csrf_protect
def toggle_event_registration(request):
    """
    Superuser-exclusive endpoint to open/close event registration platform-wide.
    Security:
    1. Requires authentication AND request.user.is_superuser == True.
    2. Enforces CSRF token and POST method.
    3. Writes immutable forensic AuditLog entry.
    """
    if request.method != 'POST':
        return redirect('dashboard:admin_dashboard')

    if not request.user.is_authenticated or not request.user.is_superuser:
        actor_name = getattr(request.user, 'email', str(request.user))
        logger.warning(
            f"[Security Alert] Unauthorized registration toggle attempt by '{actor_name}' from IP {request.META.get('REMOTE_ADDR')}"
        )
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
            return JsonResponse({
                'success': False,
                'error': 'Access Denied: Only platform superusers are authorized to open or close event registration.'
            }, status=403)
        messages.error(request, "Access Denied: Only platform superusers are authorized to open or close event registration.")
        return redirect('dashboard:admin_dashboard')

    from core.models import SystemConfiguration

    config = SystemConfiguration.get_solo()
    old_state = config.is_registration_open
    new_state = not old_state

    # Optional custom closed message
    custom_msg = request.POST.get('closed_message')
    if custom_msg and custom_msg.strip():
        config.registration_closed_message = custom_msg.strip()

    config.is_registration_open = new_state
    config.updated_by = request.user
    config.save()

    action_type = 'REGISTRATION_OPEN' if new_state else 'REGISTRATION_CLOSE'
    status_label = "OPENED" if new_state else "CLOSED"

    # Write immutable security audit record
    log_audit_event(
        actor=request.user,
        action=action_type,
        target_model='SystemConfiguration',
        target_id='1',
        details={
            'previous_state': old_state,
            'new_state': new_state,
            'closed_message': config.registration_closed_message,
        },
        request=request
    )

    logger.info(f"[Platform Control] Event registration {status_label} by superuser {request.user.email} (IP: {request.META.get('REMOTE_ADDR')})")

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
        return JsonResponse({
            'success': True,
            'is_registration_open': new_state,
            'status_label': status_label,
            'message': f"Event registration has been successfully {status_label.lower()}."
        })

    messages.success(request, f"Event registration has been successfully {status_label.lower()}.")
    return redirect('dashboard:admin_dashboard')


