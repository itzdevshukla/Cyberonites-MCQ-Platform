"""
Dashboard URL patterns.
"""
from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    # Admin Dashboard
    path('', views.admin_dashboard, name='admin_dashboard'),
    path('quizzes/', views.quiz_list, name='quiz_list'),
    path('quizzes/create/', views.quiz_create, name='quiz_create'),
    path('quizzes/<int:quiz_id>/edit/', views.quiz_edit, name='quiz_edit'),
    path('quizzes/<int:quiz_id>/delete/', views.quiz_delete, name='quiz_delete'),
    path('quizzes/<int:quiz_id>/control/', views.quiz_control_page, name='quiz_control_page'),
    path('quizzes/<int:quiz_id>/control/action/', views.quiz_control, name='quiz_control'),

    # Questions
    path('quizzes/<int:quiz_id>/questions/', views.question_list, name='question_list'),
    path('quizzes/<int:quiz_id>/questions/add/', views.question_create, name='question_create'),
    path('quizzes/<int:quiz_id>/questions/<int:question_id>/edit/', views.question_edit, name='question_edit'),
    path('quizzes/<int:quiz_id>/questions/<int:question_id>/delete/', views.question_delete, name='question_delete'),

    # Upload
    path('quizzes/<int:quiz_id>/upload/', views.upload_questions_redirect, name='upload_questions'),

    # Participants & Violations
    path('quizzes/<int:quiz_id>/participants/', views.participant_list, name='participant_list'),
    path('quizzes/<int:quiz_id>/participants/<int:participant_id>/kick/', views.quiz_kick_participant, name='quiz_kick_participant'),
    path('participants/<int:participant_id>/delete/', views.participant_delete, name='participant_delete'),
    path('quizzes/<int:quiz_id>/violations/', views.violation_list, name='violation_list'),


    # Announcements
    path('quizzes/<int:quiz_id>/announce/', views.broadcast_announcement, name='broadcast_announcement'),

    # Exports
    path('quizzes/<int:quiz_id>/export/', views.export_results, name='export_results'),

    # Participant Result
    path('result/<int:quiz_id>/', views.result_page, name='result_page'),
]
