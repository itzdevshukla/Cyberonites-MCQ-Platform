"""
Authentication views: register, login (with session enforcement), logout, admin login.
"""
import logging
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.contrib.sessions.models import Session
from django.views.decorators.http import require_http_methods

from .forms import ParticipantRegistrationForm, ParticipantLoginForm, AdminLoginForm

logger = logging.getLogger('accounts')
Participant = get_user_model()


@require_http_methods(["GET", "POST"])
def register_view(request):
    """Handle participant registration."""
    if request.user.is_authenticated:
        return redirect('quiz:lobby')

    if request.method == 'POST':
        form = ParticipantRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            # Store session key for single-session enforcement
            user.update_session(request.session.session_key)
            logger.info(f"New participant registered: {user.email}")
            messages.success(request, f"Welcome, {user.full_name}! Registration successful.")
            return redirect('quiz:lobby')
        else:
            messages.error(request, "Please fix the errors below.")
    else:
        form = ParticipantRegistrationForm()

    return render(request, 'accounts/register.html', {'form': form})


from django.db import models

@require_http_methods(["GET", "POST"])
def login_view(request):
    """Handle participant login with single-session enforcement."""
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect('dashboard:admin_dashboard')
        return redirect('quiz:lobby')

    if request.method == 'POST':
        form = ParticipantLoginForm(request.POST)
        if form.is_valid():
            input_val = form.cleaned_data['email'].lower().strip()
            password = form.cleaned_data['password']

            # Support login via email or username
            participant = Participant.objects.filter(
                models.Q(email__iexact=input_val) | models.Q(username__iexact=input_val)
            ).first()

            user = None
            if participant:
                user = authenticate(request, username=participant.username, password=password)
            else:
                user = authenticate(request, username=input_val, password=password)

            if user is not None:
                # Kill previous session if exists
                if user.session_key:
                    try:
                        old_session = Session.objects.get(session_key=user.session_key)
                        old_session.delete()
                        logger.info(f"Terminated old session for: {user.email}")
                    except Session.DoesNotExist:
                        pass

                # Login and store new session
                login(request, user)
                user.update_session(request.session.session_key)
                logger.info(f"Participant logged in: {user.email}")

                if user.is_staff:
                    return redirect('dashboard:admin_dashboard')

                messages.success(request, f"Welcome back, {user.full_name}!")
                return redirect('quiz:lobby')
            else:
                messages.error(request, "Invalid email or password.")
        else:
            messages.error(request, "Please enter valid credentials.")
    else:
        form = ParticipantLoginForm()

    return render(request, 'accounts/login.html', {'form': form})


@require_http_methods(["GET", "POST"])
def admin_login_view(request):
    """Handle admin login."""
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('dashboard:admin_dashboard')

    if request.method == 'POST':
        form = AdminLoginForm(request.POST)
        if form.is_valid():
            input_val = form.cleaned_data['username'].lower().strip()
            password = form.cleaned_data['password']

            participant = Participant.objects.filter(
                models.Q(email__iexact=input_val) | models.Q(username__iexact=input_val)
            ).first()

            user = None
            if participant:
                user = authenticate(request, username=participant.username, password=password)
            else:
                user = authenticate(request, username=input_val, password=password)

            if user is not None and user.is_staff:
                login(request, user)
                user.update_session(request.session.session_key)
                logger.info(f"Admin logged in: {user.username}")
                messages.success(request, "Welcome to the Admin Dashboard!")
                return redirect('dashboard:admin_dashboard')
            else:
                messages.error(request, "Invalid admin credentials.")
    else:
        form = AdminLoginForm()

    return render(request, 'accounts/admin_login.html', {'form': form})


def logout_view(request):
    """Handle logout and clear session."""
    if request.user.is_authenticated:
        request.user.update_session(None)
        logger.info(f"User logged out: {request.user.email}")
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect('accounts:login')
