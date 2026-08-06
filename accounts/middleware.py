"""
Middleware for single-session enforcement.
If a user logs in on another device, the previous session is invalidated.
"""
import logging
from django.shortcuts import redirect
from django.contrib.auth import logout
from django.contrib import messages

logger = logging.getLogger('accounts')


class SingleSessionMiddleware:
    """
    Ensures only one active session per participant.
    If session_key mismatch detected, forces logout with a message.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not request.user.is_staff:
            current_session = request.session.session_key
            stored_session = request.user.session_key

            if stored_session and current_session and current_session != stored_session:
                logger.warning(
                    f"Session mismatch for {request.user.email}: "
                    f"current={current_session}, stored={stored_session}"
                )
                logout(request)
                messages.warning(
                    request,
                    "Your session was terminated because your account was logged in from another device."
                )
                return redirect('accounts:login')

        response = self.get_response(request)
        return response
