"""
Custom decorators for access control.
"""
from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages


def participant_required(view_func):
    """Decorator: ensures user is authenticated participant (not staff)."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.warning(request, "Please login to continue.")
            return redirect('accounts:login')
        return view_func(request, *args, **kwargs)
    return wrapper


def admin_required(view_func):
    """Decorator: ensures user is authenticated staff/admin."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:admin_login')
        if not request.user.is_staff:
            messages.error(request, "Access denied. Admin privileges required.")
            return redirect('accounts:login')
        return view_func(request, *args, **kwargs)
    return wrapper
