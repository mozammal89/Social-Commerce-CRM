"""
Store model for multi-tenancy support in Social Commerce CRM.

This module defines the Store model which serves as the foundation for
store-based multi-tenancy. Each store represents a tenant in the system.
"""

from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

from apps.common.models import BaseModel, StatusModel
from apps.accounts.models import User


class StoreQuerySet(models.QuerySet):
    """Custom queryset for Store model."""

    def active(self):
        """Return active stores."""
        return self.filter(status="active")

    def by_owner(self, user_id):
        """Return stores owned by a specific user."""
        return self.filter(owners__id=user_id)


class StoreManager(models.Manager):
    """Custom manager for Store model."""

    def get_queryset(self):
        """Return custom queryset."""
        return StoreQuerySet(self.model, using=self._db)

    def active(self):
        """Return active stores."""
        return self.get_queryset().active()

    def by_owner(self, user_id):
        """Return stores owned by a specific user."""
        return self.get_queryset().by_owner(user_id)


class Store(BaseModel, StatusModel):
    """Store model for multi-tenancy support.

    This model represents a store/tenant in the Social Commerce CRM system.
    All domain-specific models (products, customers, orders, etc.) should
    inherit from TenantBaseModel to maintain proper data isolation.

    Attributes:
        name: Store name
        slug: URL-friendly store identifier
        description: Store description
        logo: Store logo image
        owners: Users who own the store
        managers: Users who manage the store
        staff: Users who work at the store
        status: Store status (active, inactive, pending, archived)
        settings: JSON field for store-specific settings
    """

    class Meta:
        verbose_name = _("store")
        verbose_name_plural = _("stores")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["status", "created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["slug"],
                condition=models.Q(is_deleted=False),
                name="unique_active_store_slug",
            ),
        ]

    name = models.CharField(
        _("store name"),
        max_length=255,
        db_index=True,
    )
    slug = models.SlugField(
        _("store slug"),
        max_length=255,
        unique=True,
        allow_unicode=False,
        db_index=True,
    )
    description = models.TextField(
        _("store description"),
        blank=True,
        null=True,
    )
    logo = models.ImageField(
        _("store logo"),
        upload_to="stores/logos/",
        blank=True,
        null=True,
    )
    owners = models.ManyToManyField(
        User,
        related_name="owned_stores",
        verbose_name=_("store owners"),
    )
    managers = models.ManyToManyField(
        User,
        related_name="managed_stores",
        blank=True,
        verbose_name=_("store managers"),
    )
    staff = models.ManyToManyField(
        User,
        related_name="stores",
        blank=True,
        verbose_name=_("store staff"),
    )
    settings = models.JSONField(
        _("store settings"),
        default=dict,
        blank=True,
    )

    objects = StoreManager()

    def __str__(self) -> str:
        return self.name

    def clean(self):
        """Validate store data."""
        super().clean()
        if self.slug:
            existing_slug = (
                Store.objects.filter(
                    slug=self.slug,
                    is_deleted=False,
                )
                .exclude(id=self.id)
                .exists()
            )
            if existing_slug:
                raise ValidationError(
                    {
                        "slug": _("A store with this slug already exists."),
                    }
                )

    def save(self, *args, **kwargs):
        """Save store with slug generation."""
        if not self.slug and self.name:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            while Store.objects.filter(slug=slug, is_deleted=False).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug

        self.full_clean()
        super().save(*args, **kwargs)

    def has_user_access(self, user: User) -> bool:
        """Check if user has access to this store."""
        return (
            self.owners.filter(id=user.id).exists()
            or self.managers.filter(id=user.id).exists()
            or self.staff.filter(id=user.id).exists()
        )

    def is_owner(self, user: User) -> bool:
        """Check if user is an owner of this store."""
        return self.owners.filter(id=user.id).exists()

    def is_manager(self, user: User) -> bool:
        """Check if user is a manager of this store."""
        return self.managers.filter(id=user.id).exists()

    def is_staff_member(self, user: User) -> bool:
        """Check if user is a staff member of this store."""
        return self.staff.filter(id=user.id).exists()

    def add_owner(self, user: User) -> None:
        """Add user as store owner."""
        self.owners.add(user)

    def add_manager(self, user: User) -> None:
        """Add user as store manager."""
        self.managers.add(user)

    def add_staff(self, user: User) -> None:
        """Add user as store staff."""
        self.staff.add(user)

    def remove_owner(self, user: User) -> None:
        """Remove user as store owner."""
        self.owners.remove(user)

    def remove_manager(self, user: User) -> None:
        """Remove user as store manager."""
        self.managers.remove(user)

    def remove_staff(self, user: User) -> None:
        """Remove user as store staff."""
        self.staff.remove(user)


__all__ = ["Store", "StoreManager", "StoreQuerySet"]
