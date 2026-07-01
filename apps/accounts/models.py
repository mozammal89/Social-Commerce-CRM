"""
Custom User model for Social Commerce CRM.

This module defines a custom User model with UUID primary key,
email-based authentication, and extended fields for social commerce.
"""

import uuid
from typing import TYPE_CHECKING

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import UUIDModel, TimeStampedModel, SoftDeleteModel

if TYPE_CHECKING:
    pass


class UserManager(BaseUserManager["User"]):
    """Custom user manager for email-based authentication."""

    def create_user(
        self,
        email: str,
        password: str | None = None,
        **extra_fields,
    ) -> "User":
        """Create and save a regular user with the given email and password."""
        if not email:
            raise ValueError(_("The Email field must be set"))
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(
        self,
        email: str,
        password: str | None = None,
        **extra_fields,
    ) -> "User":
        """Create and save a superuser with the given email and password."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError(_("Superuser must have is_staff=True."))
        if extra_fields.get("is_superuser") is not True:
            raise ValueError(_("Superuser must have is_superuser=True."))

        return self.create_user(email, password, **extra_fields)

    def get_by_natural_key(self, email: str) -> "User":
        """Get user by email (case-insensitive)."""
        return self.get(email__iexact=email)


class User(UUIDModel, TimeStampedModel, SoftDeleteModel, AbstractUser):
    """Custom User model for Social Commerce CRM.

    Extends AbstractUser with UUID primary key, email-based authentication,
    phone number support, and social commerce specific fields.

    Attributes:
        email: Email address (used for authentication)
        phone_number: Phone number for verification and contact
        first_name: User's first name
        last_name: User's last name
        avatar: User profile picture
        is_active: Whether the user account is active
        is_staff: Whether the user can access admin interface
        is_superuser: Whether the user has all permissions
    """

    class UserRole(models.TextChoices):
        """User role choices."""

        ADMIN = "admin", _("Admin")
        STORE_OWNER = "store_owner", _("Store Owner")
        STORE_MANAGER = "store_manager", _("Store Manager")
        STORE_STAFF = "store_staff", _("Store Staff")
        CUSTOMER = "customer", _("Customer")

    username = None

    email = models.EmailField(
        _("email address"),
        unique=True,
        db_index=True,
        error_messages={
            "unique": _("A user with that email already exists."),
        },
    )
    phone_number = models.CharField(
        _("phone number"),
        max_length=20,
        blank=True,
        null=True,
        db_index=True,
    )
    first_name = models.CharField(_("first name"), max_length=150)
    last_name = models.CharField(_("last name"), max_length=150)
    avatar = models.ImageField(
        _("avatar"),
        upload_to="users/avatars/",
        blank=True,
        null=True,
    )
    role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.CUSTOMER,
        db_index=True,
    )
    email_verified = models.BooleanField(
        _("email verified"),
        default=False,
    )
    phone_verified = models.BooleanField(
        _("phone verified"),
        default=False,
    )
    last_login_ip = models.GenericIPAddressField(
        _("last login IP"),
        null=True,
        blank=True,
    )
    login_count = models.PositiveIntegerField(
        _("login count"),
        default=0,
    )
    # Pending subscription fields (for users who subscribed but haven't created store yet)
    pending_plan_slug = models.CharField(
        _("pending subscription plan"),
        max_length=100,
        blank=True,
        null=True,
        help_text=_("Plan slug for pending subscription before store creation"),
    )
    pending_trial_start = models.BooleanField(
        _("pending trial start"),
        default=False,
        help_text=_("Whether the pending subscription should start as trial"),
    )
    pending_subscription_date = models.DateTimeField(
        _("pending subscription date"),
        blank=True,
        null=True,
        help_text=_("When the user subscribed (before store creation)"),
    )

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["is_active", "is_staff"]),
            models.Index(fields=["created_at", "is_active"]),
        ]

    def __str__(self) -> str:
        return self.email

    def get_full_name(self) -> str:
        """Return the full name for the user."""
        full_name = f"{self.first_name} {self.last_name}"
        return full_name.strip()

    def get_short_name(self) -> str:
        """Return the short name for the user."""
        return self.first_name

    @property
    def is_store_owner(self) -> bool:
        """Check if user is a store owner."""
        return self.role == self.UserRole.STORE_OWNER

    @property
    def is_store_manager(self) -> bool:
        """Check if user is a store manager."""
        return self.role == self.UserRole.STORE_MANAGER

    @property
    def is_store_staff(self) -> bool:
        """Check if user is store staff."""
        return self.role == self.UserRole.STORE_STAFF

    @property
    def is_customer(self) -> bool:
        """Check if user is a customer."""
        return self.role == self.UserRole.CUSTOMER

    def has_store_access(self, store_id: uuid.UUID) -> bool:
        """Check if user has access to a specific store."""
        if self.is_superuser or self.is_staff:
            return True
        if self.is_store_owner:
            from apps.stores.models import Store

            return Store.objects.filter(
                id=store_id,
                owners__in=[self],
            ).exists()
        return False

    def increment_login_count(self) -> None:
        """Increment the login count for the user."""
        self.login_count = models.F("login_count") + 1
        self.save(update_fields=["login_count"])

    def update_last_login_ip(self, ip_address: str) -> None:
        """Update the last login IP for the user."""
        self.last_login_ip = ip_address
        self.save(update_fields=["last_login_ip"])


# ---------------------------------------------------------------------------
# Tenant
# ---------------------------------------------------------------------------
class Tenant(UUIDModel, TimeStampedModel):
    """
    A tenant represents a workspace/organization that owns subscriptions and stores.

    This model implements the tenant-based SaaS architecture where:
    - Subscription belongs to Tenant (not individual Stores)
    - Tenant can have multiple Stores
    - All Stores under a Tenant inherit the Tenant's subscription limits
    - User owns a Tenant through ownership relationships
    """

    name = models.CharField(
        _("tenant name"), max_length=200, help_text=_("Organization or workspace name")
    )
    slug = models.SlugField(
        _("tenant slug"),
        unique=True,
        max_length=100,
        help_text=_("URL-friendly identifier for the tenant"),
    )
    owner = models.ForeignKey(
        "User",
        on_delete=models.CASCADE,
        related_name="owned_tenants",
        help_text=_("Primary owner of this tenant"),
    )
    is_active = models.BooleanField(
        _("is active"), default=True, help_text=_("Whether this tenant is active")
    )

    class Meta:
        verbose_name = _("tenant")
        verbose_name_plural = _("tenants")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["owner", "is_active"]),
            models.Index(fields=["created_at", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.slug})"


__all__ = ["User", "UserManager", "Tenant"]
