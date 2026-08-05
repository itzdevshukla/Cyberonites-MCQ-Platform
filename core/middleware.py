"""
Security and rate limiting middleware.
"""
import time
import logging
from django.http import HttpResponse

logger = logging.getLogger('django')

# Simple in-memory rate limiter (sufficient for SQLite + 200 users)
_rate_limit_cache = {}


class SecurityHeadersMiddleware:
    """Adds security headers to all responses."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # Security headers
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        return response


class RateLimitMiddleware:
    """
    Simple rate limiter for API endpoints.
    Limits to 60 requests per minute per IP.
    """
    RATE_LIMIT = 60  # requests
    WINDOW = 60  # seconds

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only rate-limit API/AJAX endpoints
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            ip = self._get_client_ip(request)
            now = time.time()

            if ip in _rate_limit_cache:
                requests, window_start = _rate_limit_cache[ip]
                if now - window_start > self.WINDOW:
                    _rate_limit_cache[ip] = (1, now)
                elif requests >= self.RATE_LIMIT:
                    logger.warning(f"Rate limit exceeded for IP: {ip}")
                    return HttpResponse("Too many requests. Please slow down.", status=429)
                else:
                    _rate_limit_cache[ip] = (requests + 1, window_start)
            else:
                _rate_limit_cache[ip] = (1, now)

        return self.get_response(request)

    @staticmethod
    def _get_client_ip(request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '0.0.0.0')
