"""
URL configuration for Quiz Platform.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect


from django.http import HttpResponse
from django.urls import re_path

urlpatterns = [
    path('django-admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('quiz/', include('quiz.urls')),
    path('imports/', include('imports.urls')),
    path('dashboard/', include('dashboard.urls')),
    path('leaderboard/', include('leaderboard.urls')),
    path('hybridaction/zybTrackerStatisticsAction', lambda request: HttpResponse(status=204)),
    re_path(r'^hybridaction/.*', lambda request: HttpResponse(status=204)),
    path('', lambda request: redirect('accounts:login'), name='home'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


def custom_404(request, exception):
    return render(request, '404.html', status=404)


def custom_500(request):
    return render(request, '500.html', status=500)


handler404 = 'quiz_platform.urls.custom_404'
handler500 = 'quiz_platform.urls.custom_500'

