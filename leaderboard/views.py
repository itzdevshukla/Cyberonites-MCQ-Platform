"""
Leaderboard views.
"""
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from quiz.models import Quiz
from .services import LeaderboardService


@login_required
def leaderboard_page(request, quiz_id):
    """Render leaderboard page (requires authenticated session)."""
    quiz = get_object_or_404(Quiz, id=quiz_id)
    entries = LeaderboardService.get_leaderboard(quiz)
    total_joined = quiz.participations.count()
    total_submitted = quiz.participations.filter(is_submitted=True).count()
    top_score = entries[0]['score'] if entries else 0
    context = {
        'quiz': quiz,
        'entries': entries,
        'total_joined': total_joined,
        'total_submitted': total_submitted,
        'top_score': top_score,
        'current_user_id': request.user.id,
    }
    return render(request, 'leaderboard/leaderboard.html', context)


@login_required
def leaderboard_data(request, quiz_id):
    """JSON API for leaderboard data (AJAX, requires authenticated session)."""
    quiz = get_object_or_404(Quiz, id=quiz_id)
    entries = LeaderboardService.get_leaderboard(quiz)
    total_joined = quiz.participations.count()
    total_submitted = quiz.participations.filter(is_submitted=True).count()
    top_score = entries[0]['score'] if entries else 0
    return JsonResponse({
        'entries': entries,
        'total_joined': total_joined,
        'total_submitted': total_submitted,
        'top_score': top_score,
    })
