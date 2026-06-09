"""
Test configuration and fixtures for Social Commerce CRM.
"""

import pytest
from rest_framework.test import APIClient


def get_user_model():
    """Get the User model."""
    from django.contrib.auth import get_user_model as _get_user_model
    return _get_user_model()


@pytest.fixture
def api_client():
    """Return an API client instance."""
    return APIClient()


@pytest.fixture
def authenticated_client(api_client, user):
    """Return an authenticated API client."""
    api_client.force_authenticate(user=user)
    return api_client


@pytest.fixture
def user(db):
    """Create and return a test user."""
    User = get_user_model()
    return User.objects.create_user(
        email="test@example.com",
        password="testpassword123",
        first_name="Test",
        last_name="User",
        phone_number="+1234567890",
    )


@pytest.fixture
def admin_user(db):
    """Create and return an admin user."""
    User = get_user_model()
    return User.objects.create_superuser(
        email="admin@example.com",
        password="adminpassword123",
        first_name="Admin",
        last_name="User",
    )


@pytest.fixture
def store_owner(db):
    """Create and return a store owner user."""
    User = get_user_model()
    return User.objects.create_user(
        email="owner@example.com",
        password="ownerpassword123",
        first_name="Store",
        last_name="Owner",
        role=User.UserRole.STORE_OWNER,
    )
