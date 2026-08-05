"""
Quiz business logic: score calculation, randomization, timer management.
"""
import random
import logging
from django.utils import timezone
from django.db.models import Sum

logger = logging.getLogger('quiz')


class QuizRandomizer:
    """
    Handles Fisher-Yates shuffle for questions and options.
    Each participant gets a unique random order stored in their participation record.
    """

    @staticmethod
    def generate_question_order(quiz):
        """Generate a shuffled list of question IDs for a quiz."""
        question_ids = list(quiz.questions.values_list('id', flat=True))
        if quiz.randomize_questions:
            random.shuffle(question_ids)
        return question_ids

    @staticmethod
    def generate_option_orders(quiz):
        """Generate shuffled option orders for each question."""
        option_orders = {}
        for question in quiz.questions.prefetch_related('options').all():
            option_ids = list(question.options.values_list('id', flat=True))
            if quiz.randomize_options:
                random.shuffle(option_ids)
            option_orders[str(question.id)] = option_ids
        return option_orders


class ScoreCalculator:
    """
    Server-side score calculation.
    NEVER trust client-side scores.
    """

    @staticmethod
    def calculate(participation):
        """
        Calculate score for a participation.
        Returns (score, correct, wrong, skipped, accuracy).
        """
        question_order = participation.question_order or []
        total_questions = len(question_order)

        answers_dict = {
            a.question_id: a
            for a in participation.answers.select_related('question', 'selected_option').all()
        }

        correct = 0
        wrong = 0
        skipped = 0
        score = 0.0

        for q_id in question_order:
            answer = answers_dict.get(q_id)
            if not answer or answer.selected_option is None:
                skipped += 1
            elif answer.selected_option.is_correct:
                correct += 1
                score += answer.question.marks
            else:
                wrong += 1
                score -= answer.question.negative_marks

        score = max(0.0, round(score, 2))
        accuracy = (correct / total_questions * 100.0) if total_questions > 0 else 0.0

        # Update participation
        participation.score = score
        participation.save(update_fields=['score'])

        logger.info(
            f"Score calculated for {participation.participant.full_name}: "
            f"score={score}, correct={correct}, wrong={wrong}, skipped={skipped}"
        )

        return {
            'score': max(0, score),
            'correct': correct,
            'wrong': wrong,
            'skipped': skipped,
            'accuracy': round(accuracy, 1),
            'total': total_questions,
        }


class TimerService:
    """
    Server-authoritative timer.
    Client timers are visual-only; server determines actual remaining time.
    """

    @staticmethod
    def get_remaining_seconds(quiz):
        """Calculate remaining seconds for an active quiz."""
        if quiz.status != 'ACTIVE':
            return 0

        now = timezone.now()
        if not quiz.end_time or now >= quiz.end_time:
            from datetime import timedelta
            quiz.start_time = now
            quiz.end_time = now + timedelta(minutes=quiz.duration_minutes)
            quiz.save(update_fields=['start_time', 'end_time'])

        remaining = (quiz.end_time - now).total_seconds()
        return max(0, int(remaining))


    @staticmethod
    def start_quiz(quiz):
        """Set quiz start and end times."""
        from datetime import timedelta
        now = timezone.now()
        quiz.start_time = now
        quiz.end_time = now + timedelta(minutes=quiz.duration_minutes)
        quiz.status = 'ACTIVE'
        quiz.save(update_fields=['start_time', 'end_time', 'status'])
        logger.info(f"Quiz started: {quiz.title}, ends at {quiz.end_time}")
        return quiz

    @staticmethod
    def stop_quiz(quiz):
        """Force stop the quiz."""
        quiz.status = 'COMPLETED'
        quiz.end_time = timezone.now()
        quiz.save(update_fields=['status', 'end_time'])
        logger.info(f"Quiz stopped: {quiz.title}")
        return quiz

    @staticmethod
    def pause_quiz(quiz):
        """Pause the quiz (freeze timer)."""
        quiz.status = 'PAUSED'
        quiz.save(update_fields=['status'])
        logger.info(f"Quiz paused: {quiz.title}")
        return quiz

    @staticmethod
    def resume_quiz(quiz, remaining_seconds=None):
        """Resume a paused quiz."""
        from datetime import timedelta
        now = timezone.now()
        if remaining_seconds:
            quiz.end_time = now + timedelta(seconds=remaining_seconds)
        quiz.status = 'ACTIVE'
        quiz.save(update_fields=['status', 'end_time'])
        logger.info(f"Quiz resumed: {quiz.title}")
        return quiz

    @staticmethod
    def extend_timer(quiz, extra_minutes):
        """Extend the quiz timer by extra minutes."""
        from datetime import timedelta
        if quiz.end_time:
            quiz.end_time += timedelta(minutes=extra_minutes)
            quiz.save(update_fields=['end_time'])
            logger.info(f"Quiz extended by {extra_minutes}min: {quiz.title}")
        return quiz

    @staticmethod
    def is_expired(quiz):
        """Check if quiz time has expired."""
        if quiz.status == 'ACTIVE':
            remaining = TimerService.get_remaining_seconds(quiz)
            return remaining <= 0
        return False

