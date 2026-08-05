"""
Leaderboard URL patterns.
"""
from django.urls import path
from . import views

app_name = 'leaderboard'

urlpatterns = [
    path('<int:quiz_id>/', views.leaderboard_page, name='leaderboard'),
    path('<int:quiz_id>/data/', views.leaderboard_data, name='data'),
]
