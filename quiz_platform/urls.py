"""
URL configuration for Quiz Platform.
"""
import logging
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import render, redirect


from django.http import HttpResponse
from django.urls import re_path
from accounts import views as accounts_views

def landing_view(request):
    quizzes = []
    try:
        from quiz.models import Quiz
        quizzes = Quiz.objects.filter(status__in=['ACTIVE', 'DRAFT', 'COMPLETED']).order_by('-created_at')[:6]
    except Exception:
        pass
    return render(request, 'landing.html', {'quizzes': quizzes})


urlpatterns = [
    path('django-admin/', admin.site.urls),
    # Fortified Secret Admin Access Point
    path('byteviper_hackvajra_bitty_bold_shadow_cache/', accounts_views.admin_login_view, name='secret_admin_login'),
    path('byteviper_hackvajra_bitty_bold_shadow_cache', accounts_views.admin_login_view),
    path('accounts/', include('accounts.urls')),
    path('quiz/', include('quiz.urls')),
    path('imports/', include('imports.urls')),
    path('dashboard/', include('dashboard.urls')),
    path('leaderboard/', include('leaderboard.urls')),
    path('favicon.ico', lambda request: HttpResponse(status=204)),
    path('hybridaction/zybTrackerStatisticsAction', lambda request: HttpResponse(status=204)),
    re_path(r'^hybridaction/.*', lambda request: HttpResponse(status=204)),
    path('', landing_view, name='home'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


logger = logging.getLogger('django')


def custom_404(request, exception):
    return render(request, '404.html', status=404)


def custom_500(request):
    import sys
    logger.error("Unhandled 500 Server Error on %s: %s", request.path, sys.exc_info(), exc_info=True)
    return render(request, '500.html', status=500)


handler404 = 'quiz_platform.urls.custom_404'
handler500 = 'quiz_platform.urls.custom_500'


