"""
Global template context processors.
"""
from quiz.models import Quiz


def global_context(request):
    """Add global context variables available in all templates."""
    context = {
        'site_name': 'QArena',
        'site_tagline': 'Secure Quizzes. Controlled Exams. Zero Compromise.',
    }


    try:
        active_quiz = Quiz.objects.filter(status='ACTIVE').first()
        context['active_quiz'] = active_quiz
    except Exception:
        context['active_quiz'] = None

    # Global Event Registration Status
    try:
        from core.models import SystemConfiguration
        sys_config = SystemConfiguration.get_solo()
        context['is_registration_open'] = sys_config.is_registration_open
        context['registration_closed_message'] = sys_config.registration_closed_message
    except Exception:
        context['is_registration_open'] = True
        context['registration_closed_message'] = ''

    user_agent = request.META.get('HTTP_USER_AGENT', '')
    context['is_secure_browser'] = (
        'CyberonitesSecureBrowser' in user_agent
        or bool(request.headers.get('X-Secure-App-Signature'))
        or bool(request.headers.get('X-Secure-App-Timestamp'))
    )

    return context
