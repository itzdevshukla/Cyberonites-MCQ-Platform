"""
Shared utility functions.
"""


def get_client_ip(request):
    """Extract client IP from request, handling proxies."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
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
