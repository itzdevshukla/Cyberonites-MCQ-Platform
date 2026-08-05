"""
Quiz URL patterns.
"""
from django.urls import path
from . import views

app_name = 'quiz'

urlpatterns = [
    path('', views.quiz_lobby, name='lobby'),
    path('<int:quiz_id>/start/', views.quiz_start, name='start'),
    path('<int:quiz_id>/take/', views.take_quiz, name='take_quiz'),
    path('<int:quiz_id>/question/<int:question_index>/', views.get_question, name='get_question'),
    path('<int:quiz_id>/save-answer/', views.save_answer, name='save_answer'),
    path('<int:quiz_id>/submit/', views.submit_quiz, name='submit'),
    path('<int:quiz_id>/status/', views.quiz_status, name='status'),
    path('<int:quiz_id>/violation/', views.report_violation, name='report_violation'),
]
