from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.http import JsonResponse
from .models import Quiz
from core.secure_app import verify_secure_app_request

def require_secure_browser(view_func):
    """
    Decorator to ensure that the view is accessed via the Secure Exam Browser
    if the quiz is marked as proctored.
    Cryptographically verifies dynamic HMAC-SHA256 signature, timestamp window, and nonce.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        quiz_id = kwargs.get('quiz_id')
        if not quiz_id:
            return view_func(request, *args, **kwargs)
            
        quiz = Quiz.objects.filter(id=quiz_id).first()
        if quiz and quiz.is_proctored:
            is_valid, reason = verify_secure_app_request(request, quiz_id=quiz.id)
            if not is_valid:
                # If it's an AJAX request, return JSON
                if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
                    return JsonResponse({
                        'error': 'Please use the official Secure Exam Browser to take this proctored quiz.',
                        'security_reason': reason
                    }, status=403)
                
                # Otherwise, redirect to a "Download App" page
                messages.error(request, f"Proctored Exam Security: {reason}. Please launch the Secure Exam Browser.")
                return redirect('quiz:secure_app_download')
                
        return view_func(request, *args, **kwargs)
        
    return _wrapped_view
