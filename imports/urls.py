"""
Import URL patterns.
"""
from django.urls import path
from . import views

app_name = 'imports'

urlpatterns = [
    path('upload/<int:quiz_id>/', views.upload_questions, name='upload'),
    path('template/', views.download_template, name='download_template'),
]
