"""
Template tags for Social Commerce CRM.

This module was refactored from a single .py file into a proper
templatetags package so Django can discover it under INSTALLED_APPS.

Existing tag names (user_name, user_initials, add_css_class, etc.) are
preserved for backward compatibility.
"""

from django import template
from django.contrib.auth import get_user_model

register = template.Library()

User = get_user_model()


@register.simple_tag
def user_name(user):
    """Get the user's full name."""
    return user.get_full_name() if user else ""


@register.simple_tag
def user_initials(user):
    """Get user's initials."""
    if not user:
        return "U"
    first_initial = user.first_name[0].upper() if user.first_name else ""
    last_initial = user.last_name[0].upper() if user.last_name else ""
    return f"{first_initial}{last_initial}"


@register.simple_tag
def user_avatar(user):
    """Get user avatar image or placeholder."""
    if not user:
        return "/static/images/default-avatar.png"
    if user.avatar:
        return user.avatar.url
    return "/static/images/default-avatar.png"


@register.filter
def add_css_class(field, css_class):
    """Add CSS class to form field."""
    return field.as_widget(
        attrs={"class": f"{field.field.widget.attrs.get('class', '')} {css_class}"}
    )


@register.simple_tag
def dict_get(dictionary, key, default=""):
    """Get value from dictionary with default."""
    return dictionary.get(key, default)


@register.simple_tag
def dict_has(dictionary, key):
    """Check if dictionary has key."""
    return key in dictionary


@register.simple_tag
def get_item(dictionary, key, default=None):
    """Get item from dictionary using dot notation."""
    keys = key.split(".")
    value = dictionary
    for k in keys:
        if hasattr(value, "__getitem__"):
            value = value[k]
        else:
            return default
    return value


@register.simple_tag
def is_active(request, pattern_name):
    """Check if the current URL matches the pattern."""
    if not request or not hasattr(request, "resolver_match"):
        return False
    return request.resolver_match.url_name == pattern_name


@register.simple_tag
def get_status_badge_class(status):
    """Get Bootstrap badge class for status."""
    status_classes = {
        "active": "bg-success",
        "inactive": "bg-danger",
        "pending": "bg-warning",
        "archived": "bg-secondary",
        "open": "bg-success",
        "closed": "bg-danger",
        "processing": "bg-warning",
        "completed": "bg-info",
    }
    return status_classes.get(status.lower(), "bg-secondary")
