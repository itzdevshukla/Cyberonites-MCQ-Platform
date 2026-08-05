"""
Leaderboard views.
"""
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from quiz.models import Quiz
from .services import LeaderboardService


def leaderboard_page(request, quiz_id):
    """Render leaderboard page."""
    quiz = get_object_or_404(Quiz, id=quiz_id)
    entries = LeaderboardService.get_leaderboard(quiz)
    context = {
        'quiz': quiz,
        'entries': entries,
    }
    return render(request, 'leaderboard/leaderboard.html', context)


def leaderboard_data(request, quiz_id):
    """JSON API for leaderboard data (AJAX)."""
    quiz = get_object_or_404(Quiz, id=quiz_id)
    entries = LeaderboardService.get_leaderboard(quiz)
    return JsonResponse({'entries': entries})
