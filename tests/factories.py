"""
Factory classes for User model.
"""

import factory
from factory import fuzzy
from apps.accounts.models import User


class UserFactory(factory.django.DjangoModelFactory):
    """Factory for creating User instances."""

    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    phone_number = factory.Faker("phone_number")
    role = fuzzy.FuzzyChoice([role[0] for role in User.UserRole.choices])
    is_active = True
    is_staff = False
    is_superuser = False
    email_verified = False
    phone_verified = False

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        """Set password for user."""
        password = extracted or "testpassword123"
        self.set_password(password)
        if create:
            self.save()


class AdminUserFactory(UserFactory):
    """Factory for creating admin users."""

    is_staff = True
    is_superuser = True
    role = User.UserRole.ADMIN


class StoreOwnerFactory(UserFactory):
    """Factory for creating store owners."""

    role = User.UserRole.STORE_OWNER
