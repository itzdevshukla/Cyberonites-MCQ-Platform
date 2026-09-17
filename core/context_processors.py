"""
Global template context processors.
"""
from quiz.models import Quiz


def global_context(request):
    """Add global context variables available in all templates."""
    context = {
        'site_name': 'Qarena',
        'site_tagline': 'Secure Quizzes. Controlled Exams. Zero Compromise.',
    }


    # Add active quiz info if available
    try:
        active_quiz = Quiz.objects.filter(status='ACTIVE').first()
        context['active_quiz'] = active_quiz
    except Exception:
        context['active_quiz'] = None

    user_agent = request.META.get('HTTP_USER_AGENT', '')
    context['is_secure_browser'] = (
        'CyberonitesSecureBrowser' in user_agent
        or bool(request.headers.get('X-Secure-App-Signature'))
        or bool(request.headers.get('X-Secure-App-Timestamp'))
    )

    return context
