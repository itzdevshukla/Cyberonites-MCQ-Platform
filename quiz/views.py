"""
Quiz views: lobby, quiz start, question API, answer save, submit.
Security: NEVER expose correct answers to the frontend.
"""
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.utils import timezone
from django.db import transaction, models
from django.contrib import messages
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.csrf import csrf_protect


from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from accounts.decorators import participant_required
from core.utils import get_client_ip
from core.models import ViolationLog
from .models import Quiz, Question, Option, QuizParticipation, Answer
from .services import QuizRandomizer, ScoreCalculator, TimerService

logger = logging.getLogger('quiz')


@participant_required
def quiz_lobby(request):
    """Lobby page displaying all available quizzes for the student."""
    quizzes = Quiz.objects.all().order_by('-created_at')

    # Get student's participation map { quiz_id: participation_obj }
    participations = {}
    if request.user.is_authenticated:
        p_qs = QuizParticipation.objects.filter(participant=request.user)
        participations = {p.quiz_id: p for p in p_qs}

    context = {
        'quizzes': quizzes,
        'participations': participations,
    }
    return render(request, 'quiz/lobby.html', context)


def _sync_question_orders(quiz, participation):
    """Ensure participation question_order and option_orders are populated and in sync."""
    current_q_ids = list(quiz.questions.values_list('id', flat=True))
    stored_q_ids = participation.question_order or []

    # If empty or count mismatch, update stored question_order
    if not stored_q_ids or set(current_q_ids) != set(stored_q_ids):
        participation.question_order = QuizRandomizer.generate_question_order(quiz)
        participation.option_orders = QuizRandomizer.generate_option_orders(quiz)
        participation.save(update_fields=['question_order', 'option_orders'])
    return participation


def _broadcast_participant_joined(quiz, participation):
    """Broadcast participant joined event to quiz group for live admin updates."""
    try:
        channel_layer = get_channel_layer()
        if not channel_layer:
            return
        active_count = QuizParticipation.objects.filter(quiz=quiz, is_submitted=False).count()
        total_count = QuizParticipation.objects.filter(quiz=quiz).count()
        async_to_sync(channel_layer.group_send)(
            f'quiz_{quiz.id}',
            {
                'type': 'participant_joined',
                'participant_id': participation.participant.id,
                'participant_name': participation.participant.full_name,
                'college': getattr(participation.participant, 'college', ''),
                'email': getattr(participation.participant, 'email', ''),
                'active_count': active_count,
                'total_participants': total_count,
                'timestamp': timezone.now().isoformat(),
            }
        )
    except Exception as e:
        logger.error(f"Failed to broadcast participant_joined: {e}")


def _broadcast_participant_submitted(quiz, participation, result=None):
    """Broadcast participant submitted event to quiz group for live admin updates."""
    try:
        channel_layer = get_channel_layer()
        if not channel_layer:
            return
        active_count = QuizParticipation.objects.filter(quiz=quiz, is_submitted=False).count()
        submitted_count = QuizParticipation.objects.filter(quiz=quiz, is_submitted=True).count()
        score = result['score'] if (result and 'score' in result) else participation.score
        async_to_sync(channel_layer.group_send)(
            f'quiz_{quiz.id}',
            {
                'type': 'participant_submitted',
                'participant_id': participation.participant.id,
                'participant_name': participation.participant.full_name,
                'score': score,
                'time_taken': participation.time_taken or 0,
                'active_count': active_count,
                'submitted_count': submitted_count,
                'timestamp': timezone.now().isoformat(),
            }
        )
    except Exception as e:
        logger.error(f"Failed to broadcast participant_submitted: {e}")


def _broadcast_violation_reported(quiz, participation, violation_log):
    """Broadcast violation event to quiz group for live admin updates."""
    try:
        channel_layer = get_channel_layer()
        if not channel_layer:
            return
        async_to_sync(channel_layer.group_send)(
            f'quiz_{quiz.id}',
            {
                'type': 'violation_reported',
                'participant_id': participation.participant.id,
                'participant_name': participation.participant.full_name,
                'violation_type': violation_log.violation_type,
                'details': violation_log.details,
                'ip_address': violation_log.ip_address or '-',
                'violation_count': participation.violation_count,
                'created_at': violation_log.created_at.strftime('%H:%M:%S'),
            }
        )
    except Exception as e:
        logger.error(f"Failed to broadcast violation_reported: {e}")


@participant_required
@require_http_methods(["POST"])
@csrf_protect
def quiz_start(request, quiz_id):
    """Initialize quiz participation with shuffled questions/options."""
    quiz = Quiz.objects.filter(id=quiz_id).first()
    if not quiz:
        # Fallback to active quiz if quiz_id not found
        quiz = Quiz.objects.filter(status='ACTIVE').first()

    if not quiz:
        messages.error(request, "No active quiz is currently available.")
        return redirect('quiz:lobby')

    if quiz.status != 'ACTIVE':
        messages.error(request, f"Quiz '{quiz.title}' is not currently active.")
        return redirect('quiz:lobby')

    # Check existing participation
    existing_p = QuizParticipation.objects.filter(quiz=quiz, participant=request.user).first()

    # Validate access code if required and not already participating
    if quiz.access_code and not existing_p:
        entered_code = request.POST.get('access_code', '').strip()
        if entered_code != quiz.access_code:
            messages.error(request, f"Invalid access code for '{quiz.title}'. Please ask the organizer.")
            return redirect('quiz:lobby')

    # Check or create participation atomically
    try:
        with transaction.atomic():
            participation, created = QuizParticipation.objects.get_or_create(
                quiz=quiz,
                participant=request.user,
                defaults={
                    'question_order': QuizRandomizer.generate_question_order(quiz),
                    'option_orders': QuizRandomizer.generate_option_orders(quiz),
                }
            )
    except Exception as e:
        logger.error(f"Error creating participation for {request.user.email}: {e}")
        participation = QuizParticipation.objects.filter(quiz=quiz, participant=request.user).first()

    if not participation:
        messages.error(request, "Could not initialize quiz participation. Please try again.")
        return redirect('quiz:lobby')

    _sync_question_orders(quiz, participation)

    if participation.is_submitted:
        messages.info(request, "You have already submitted this quiz.")
        return redirect('dashboard:result_page', quiz_id=quiz.id)

    _broadcast_participant_joined(quiz, participation)
    logger.info(f"Quiz started by {request.user.full_name}")
    return redirect('quiz:take_quiz', quiz_id=quiz.id)


@participant_required
def take_quiz(request, quiz_id):
    """Main quiz interface page with graceful error handling."""
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

    _sync_question_orders(quiz, participation)

    if participation.is_submitted:
        return redirect('dashboard:result_page', quiz_id=quiz.id)

    remaining = TimerService.get_remaining_seconds(quiz)

    # Check if quiz expired
    if remaining <= 0 and quiz.status == 'ACTIVE':
        # Auto-submit
        _auto_submit(participation, quiz)
        return redirect('dashboard:result_page', quiz_id=quiz.id)

    context = {
        'quiz': quiz,
        'participation': participation,
        'remaining_seconds': remaining,
        'total_questions': len(participation.question_order),
    }
    return render(request, 'quiz/quiz.html', context)


@participant_required
@require_http_methods(["GET"])
def get_question(request, quiz_id, question_index):
    """
    Fetch a single question by index (AJAX).
    SECURITY: Never returns correct answer info.
    """
    quiz = Quiz.objects.filter(id=quiz_id).first()
    if not quiz:
        return JsonResponse({'error': 'Quiz not found.'}, status=404)

    participation = QuizParticipation.objects.filter(
        quiz=quiz, participant=request.user
    ).first()

    if not participation:
        return JsonResponse({'error': 'Participation record not found.'}, status=404)

    _sync_question_orders(quiz, participation)

    if participation.is_submitted:
        return JsonResponse({'error': 'Quiz already submitted.'}, status=400)

    question_order = participation.question_order or []
    if question_index < 0 or question_index >= len(question_order):
        return JsonResponse({'error': 'Invalid question index.'}, status=400)

    question_id = question_order[question_index]
    question = Question.objects.filter(id=question_id).first()
    if not question:
        return JsonResponse({'error': 'Question not found.'}, status=404)

    # Get option order for this question (fallback if missing)
    option_order = (participation.option_orders or {}).get(str(question_id))
    if not option_order:
        option_order = list(question.options.values_list('id', flat=True))
        if quiz.randomize_options:
            import random
            random.shuffle(option_order)
        if not participation.option_orders:
            participation.option_orders = {}
        participation.option_orders[str(question_id)] = option_order
        participation.save(update_fields=['option_orders'])

    options = []
    for opt_id in option_order:
        try:
            opt = Option.objects.get(id=opt_id)
            options.append({
                'id': opt.id,
                'label': opt.label,
                'text': opt.text,
                # SECURITY: is_correct is NEVER sent
            })
        except Option.DoesNotExist:
            continue


    # Check if already answered
    existing_answer = Answer.objects.filter(
        participation=participation, question=question
    ).first()

    data = {
        'question_id': question.id,
        'question_index': question_index,
        'text': question.text,
        'topic': question.topic,
        'difficulty': question.difficulty,
        'marks': question.marks,
        'negative_marks': question.negative_marks,
        'options': options,
        'selected_option_id': existing_answer.selected_option_id if existing_answer else None,
        'is_marked_for_review': existing_answer.is_marked_for_review if existing_answer else False,
        'total_questions': len(question_order),
    }
    return JsonResponse(data)


@participant_required
@require_POST
@csrf_protect
def save_answer(request, quiz_id):
    """
    Auto-save answer (AJAX) with atomic transaction safety against race conditions.
    """
    quiz = Quiz.objects.filter(id=quiz_id).first()
    if not quiz:
        return JsonResponse({'error': 'Quiz not found.'}, status=404)

    if quiz.status not in ['ACTIVE', 'PAUSED']:
        return JsonResponse({'error': 'Quiz is not active.'}, status=400)

    import json
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid data.'}, status=400)

    question_id = body.get('question_id')
    selected_option_id = body.get('selected_option_id')
    is_marked_for_review = body.get('is_marked_for_review', False)

    question = Question.objects.filter(id=question_id, quiz=quiz).first()
    if not question:
        return JsonResponse({'error': 'Question not found.'}, status=404)

    selected_option = None
    is_correct = False
    if selected_option_id:
        selected_option = Option.objects.filter(id=selected_option_id, question=question).first()
        if not selected_option:
            return JsonResponse({'error': 'Invalid option.'}, status=400)
        is_correct = selected_option.is_correct

    with transaction.atomic():
        participation = QuizParticipation.objects.filter(
            quiz=quiz, participant=request.user
        ).first()

        if not participation:
            return JsonResponse({'error': 'Participation not found.'}, status=404)

        if participation.is_submitted:
            return JsonResponse({'error': 'Quiz already submitted.'}, status=400)

        answer, created = Answer.objects.update_or_create(
            participation=participation,
            question=question,
            defaults={
                'selected_option': selected_option,
                'is_correct': is_correct,
                'is_marked_for_review': is_marked_for_review,
            }
        )

    return JsonResponse({
        'status': 'saved',
        'question_id': question_id,
        'is_marked_for_review': is_marked_for_review,
        'has_answer': selected_option is not None,
    })


@participant_required
@require_POST
@csrf_protect
def submit_quiz(request, quiz_id):
    """
    Submit the quiz safely. Atomically prevents double-submission race conditions.
    """
    quiz = Quiz.objects.filter(id=quiz_id).first()
    if not quiz:
        return JsonResponse({'error': 'Quiz not found.'}, status=404)

    with transaction.atomic():
        participation = QuizParticipation.objects.select_for_update().filter(
            quiz=quiz, participant=request.user
        ).first()

        if not participation:
            return JsonResponse({'error': 'Participation not found.'}, status=404)

        if participation.is_submitted:
            return JsonResponse({'error': 'Already submitted.'}, status=400)

        # Calculate score server-side
        result = ScoreCalculator.calculate(participation)

        # Mark as submitted
        participation.is_submitted = True
        participation.finished_at = timezone.now()
        participation.time_taken = (
            participation.finished_at - participation.started_at
        ).total_seconds()
        participation.save(update_fields=['is_submitted', 'finished_at', 'time_taken'])

    logger.info(f"Quiz submitted by {request.user.full_name}: score={result['score']}")

    # Trigger leaderboard and live dashboard update
    _update_leaderboard(quiz, participation, result)
    _broadcast_participant_submitted(quiz, participation, result)

    return JsonResponse({'status': 'submitted', 'score': result['score']})


@participant_required
@require_http_methods(["GET"])
def quiz_status(request, quiz_id):
    """Return real-time quiz status and remaining time (AJAX)."""
    quiz = Quiz.objects.filter(id=quiz_id).first()
    if not quiz:
        return JsonResponse({'error': 'Quiz not found.'}, status=404)

    remaining = TimerService.get_remaining_seconds(quiz)
    participation = QuizParticipation.objects.filter(
        quiz=quiz, participant=request.user
    ).first()

    # Auto-submit if time expired
    if remaining <= 0 and quiz.status == 'ACTIVE' and participation and not participation.is_submitted:
        _auto_submit(participation, quiz)

    # Get answer summary for question palette
    answer_summary = []
    total_questions = 0
    if participation:
        total_questions = len(participation.question_order or [])
        answers = Answer.objects.filter(participation=participation).values(
            'question_id', 'selected_option_id', 'is_marked_for_review'
        )
        answer_summary = list(answers)

    return JsonResponse({
        'status': quiz.status,
        'remaining_seconds': remaining,
        'is_submitted': participation.is_submitted if participation else False,
        'answer_summary': answer_summary,
        'total_questions': total_questions,
    })


@participant_required
@require_POST
@csrf_protect
def report_violation(request, quiz_id):
    """Record an anti-cheat violation atomically to avoid race conditions."""
    quiz = get_object_or_404(Quiz, id=quiz_id)

    import json
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid data.'}, status=400)

    violation_type = body.get('type', 'OTHER')
    details = body.get('details', '')

    auto_submitted = False
    with transaction.atomic():
        participation = QuizParticipation.objects.filter(
            quiz=quiz, participant=request.user
        ).first()

        if not participation or participation.is_submitted:
            return JsonResponse({'status': 'already_submitted'})

        # Log violation
        v_log = ViolationLog.objects.create(
            participant=request.user,
            quiz=quiz,
            violation_type=violation_type,
            details=details,
            ip_address=get_client_ip(request),
        )

        # Atomic SQL increment: violation_count = violation_count + 1
        QuizParticipation.objects.filter(id=participation.id).update(
            violation_count=models.F('violation_count') + 1
        )
        participation.refresh_from_db(fields=['violation_count'])

        _broadcast_violation_reported(quiz, participation, v_log)

        if quiz.max_violations > 0 and participation.violation_count >= quiz.max_violations:
            _auto_submit(participation, quiz)
            auto_submitted = True

    return JsonResponse({
        'status': 'recorded',
        'violation_count': participation.violation_count,
        'max_violations': quiz.max_violations,
        'auto_submitted': auto_submitted,
    })


def _auto_submit(participation, quiz):
    """Internal: auto-submit a participation."""
    with transaction.atomic():
        p = QuizParticipation.objects.filter(id=participation.id).first()
        if not p or p.is_submitted:
            return

        result = ScoreCalculator.calculate(p)
        p.is_submitted = True
        p.finished_at = timezone.now()
        p.time_taken = (
            p.finished_at - p.started_at
        ).total_seconds()
        p.save(update_fields=['is_submitted', 'finished_at', 'time_taken'])

        _update_leaderboard(quiz, p, result)
        _broadcast_participant_submitted(quiz, p, result)
        logger.info(f"Auto-submitted quiz for {p.participant.full_name}")


def _update_leaderboard(quiz, participation, result):
    """Internal: update leaderboard entry after submission."""
    from leaderboard.models import LeaderboardEntry

    LeaderboardEntry.objects.update_or_create(
        quiz=quiz,
        participant=participation.participant,
        defaults={
            'score': result['score'],
            'accuracy': result['accuracy'],
            'time_taken': participation.time_taken or 0,
            'questions_attempted': result['correct'] + result['wrong'],
            'correct_answers': result['correct'],
            'wrong_answers': result['wrong'],
        }
    )

    # Recalculate ranks
    from leaderboard.services import LeaderboardService
    LeaderboardService.recalculate_ranks(quiz)
