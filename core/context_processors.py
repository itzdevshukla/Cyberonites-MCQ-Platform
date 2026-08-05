"""
Global template context processors.
"""
from quiz.models import Quiz


def global_context(request):
    """Add global context variables available in all templates."""
    context = {
        'site_name': 'Cyberonites',
        'site_tagline': 'The Ultimate Cyber Competition Arena',
    }


    # Add active quiz info if available
    try:
        active_quiz = Quiz.objects.filter(status='ACTIVE').first()
        context['active_quiz'] = active_quiz
    except Exception:
        context['active_quiz'] = None

    return context
