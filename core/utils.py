"""
Shared utility functions.
"""


def get_client_ip(request):
    """
    Extract client IP securely from request headers.
    Prioritizes Nginx-verified HTTP_X_REAL_IP to prevent X-Forwarded-For spoofing.
    """
    x_real_ip = request.META.get('HTTP_X_REAL_IP')
    if x_real_ip:
        return x_real_ip.strip()

    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        # Behind reverse proxies, rightmost IP is appended by the ingress proxy
        parts = [ip.strip() for ip in x_forwarded_for.split(',') if ip.strip()]
        if parts:
            return parts[-1]

    return request.META.get('REMOTE_ADDR', '0.0.0.0')


def format_duration(seconds):
    """Format seconds into HH:MM:SS string."""
    if seconds is None:
        return "N/A"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def calculate_percentile(rank, total_participants):
    """Calculate percentile based on rank."""
    if total_participants <= 1:
        return 100.0
    return round(((total_participants - rank) / (total_participants - 1)) * 100, 1)
