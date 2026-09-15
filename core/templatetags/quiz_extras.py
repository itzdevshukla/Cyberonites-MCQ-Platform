"""
Custom template tags and filters.
"""
from django import template
from core.utils import format_duration

register = template.Library()


@register.filter
def duration(seconds):
    """Format seconds to MM:SS or HH:MM:SS."""
    return format_duration(seconds)


@register.filter
def percentage(value, total):
    """Calculate percentage."""
    if not total or total == 0:
        return 0
    return round((value / total) * 100, 1)


@register.filter
def letter_index(index):
    """Convert 0-based index to letter (A, B, C, D)."""
    letters = ['A', 'B', 'C', 'D', 'E', 'F']
    if 0 <= index < len(letters):
        return letters[index]
    return str(index)


@register.filter
def get_item(dictionary, key):
    """Get item from dictionary by key."""
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None
