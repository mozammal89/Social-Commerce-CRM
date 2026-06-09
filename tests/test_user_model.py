"""
Tests for User model.
"""

import pytest
from apps.accounts.models import UserManager


def get_user_model():
    """Get the User model."""
    from django.contrib.auth import get_user_model as _get_user_model
    return _get_user_model()


@pytest.mark.django_db
class TestUserModel:
    """Test cases for User model."""

    def test_create_user(self):
        """Test creating a regular user."""
        User = get_user_model()
        user = User.objects.create_user(
            email="test@example.com",
            password="testpassword123",
            first_name="Test",
            last_name="User",
        )

        assert user.email == "test@example.com"
        assert user.check_password("testpassword123")
        assert user.first_name == "Test"
        assert user.last_name == "User"
        assert user.role == User.UserRole.CUSTOMER
        assert not user.is_staff
        assert not user.is_superuser

    def test_create_superuser(self):
        """Test creating a superuser."""
        User = get_user_model()
        user = User.objects.create_superuser(
            email="admin@example.com",
            password="adminpassword123",
            first_name="Admin",
            last_name="User",
        )

        assert user.email == "admin@example.com"
        assert user.check_password("adminpassword123")
        assert user.is_staff
        assert user.is_superuser
        assert user.role == User.UserRole.ADMIN

    def test_user_email_normalized(self):
        """Test that user email is normalized."""
        User = get_user_model()
        email = "test@EXAMPLE.COM"
        user = User.objects.create_user(
            email=email,
            password="testpassword123",
            first_name="Test",
            last_name="User",
        )

        assert user.email == email.lower()

    def test_user_str_representation(self):
        """Test user string representation."""
        User = get_user_model()
        user = User.objects.create_user(
            email="test@example.com",
            password="testpassword123",
            first_name="Test",
            last_name="User",
        )

        assert str(user) == "test@example.com"

    def test_get_full_name(self):
        """Test get_full_name method."""
        User = get_user_model()
        user = User.objects.create_user(
            email="test@example.com",
            password="testpassword123",
            first_name="John",
            last_name="Doe",
        )

        assert user.get_full_name() == "John Doe"

    def test_get_short_name(self):
        """Test get_short_name method."""
        User = get_user_model()
        user = User.objects.create_user(
            email="test@example.com",
            password="testpassword123",
            first_name="John",
            last_name="Doe",
        )

        assert user.get_short_name() == "John"

    def test_create_user_without_email(self):
        """Test that creating user without email raises error."""
        User = get_user_model()
        with pytest.raises(ValueError):
            User.objects.create_user(
                email="",
                password="testpassword123",
            )

    def test_create_superuser_without_is_staff(self):
        """Test that creating superuser without is_staff raises error."""
        User = get_user_model()
        with pytest.raises(ValueError):
            User.objects.create_superuser(
                email="admin@example.com",
                password="adminpassword123",
                is_staff=False,
            )

    def test_create_superuser_without_is_superuser(self):
        """Test that creating superuser without is_superuser raises error."""
        User = get_user_model()
        with pytest.raises(ValueError):
            User.objects.create_superuser(
                email="admin@example.com",
                password="adminpassword123",
                is_superuser=False,
            )


@pytest.mark.django_db
class TestUserManager:
    """Test cases for UserManager."""

    def test_get_by_natural_key_case_insensitive(self):
        """Test that get_by_natural_key is case-insensitive."""
        User = get_user_model()
        user = User.objects.create_user(
            email="test@EXAMPLE.COM",
            password="testpassword123",
        )

        retrieved_user = User.objects.get_by_natural_key("test@example.com")
        assert retrieved_user == user
