"""
Celery tasks for accounts app.
"""

from celery import shared_task
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import OutstandingToken, BlacklistedToken

User = get_user_model()


@shared_task
def cleanup_refresh_tokens():
    """Clean up expired refresh tokens."""
    expired_tokens = OutstandingToken.objects.filter(expires_at__lt=timezone.now())
    count = expired_tokens.count()
    expired_tokens.delete()
    return f"Cleaned up {count} expired refresh tokens"


@shared_task
def send_welcome_email(user_id):
    """Send welcome email to new user."""
    try:
        user = User.objects.get(id=user_id)
        return f"Welcome email sent to {user.email}"
    except User.DoesNotExist:
        return f"User with id {user_id} not found"


@shared_task
def update_user_login_count(user_id):
    """Increment user login count."""
    try:
        user = User.objects.get(id=user_id)
        user.increment_login_count()
        return f"Updated login count for user {user.email}"
    except User.DoesNotExist:
        return f"User with id {user_id} not found"
