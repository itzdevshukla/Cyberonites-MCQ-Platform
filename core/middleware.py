"""
Security and rate limiting middleware.
"""
import time
import logging
from django.http import HttpResponse

logger = logging.getLogger('django')

from django.core.cache import cache
from core.utils import get_client_ip

logger = logging.getLogger('django.security')


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
    Robust, cache-backed sliding window rate limiter.
    
    Features:
    - User-based rate limiting for authenticated candidates (prevents campus NAT collisions).
    - IP-based rate limiting for anonymous requests (prevents brute-force on login/register).
    - Evaluates all API, AJAX, and auth endpoints regardless of custom headers.
    - Uses Django cache with automatic TTL expiration (no memory leaks).
    """
    AUTH_USER_LIMIT = 120    # requests per minute for authenticated students
    ANON_IP_LIMIT = 30       # requests per minute for anonymous users
    WINDOW_SECONDS = 60      # 1 minute sliding window

    # Paths to exempt from rate limiting (static assets)
    EXEMPT_PREFIXES = ('/static/', '/media/', '/favicon.ico')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path

        # Skip static files
        if any(path.startswith(prefix) for prefix in self.EXEMPT_PREFIXES):
            return self.get_response(request)

        # Determine rate limit key & threshold
        if hasattr(request, 'user') and request.user.is_authenticated:
            # Per-user limit prevents 200 students sharing campus Wi-Fi from colliding
            rate_key = f"rl:user:{request.user.id}"
            limit = self.AUTH_USER_LIMIT
        else:
            client_ip = get_client_ip(request)
            rate_key = f"rl:ip:{client_ip}"
            limit = self.ANON_IP_LIMIT

        # Sliding window counter via cache
        current_count = cache.get(rate_key, 0)
        if current_count >= limit:
            logger.warning(f"Rate limit exceeded for {rate_key} on {path}")
            return HttpResponse(
                "Too many requests. Please slow down and try again in a moment.",
                status=429,
                content_type="text/plain"
            )

        # Increment count atomically with window TTL
        if current_count == 0:
            cache.set(rate_key, 1, timeout=self.WINDOW_SECONDS)
        else:
            try:
                cache.incr(rate_key)
            except Exception:
                cache.set(rate_key, current_count + 1, timeout=self.WINDOW_SECONDS)

        return self.get_response(request)
