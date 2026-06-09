"""
Abstract base models for Social Commerce CRM.

This module provides reusable base models that should be inherited
by domain-specific models throughout the application.
"""

import uuid
from typing import TYPE_CHECKING

from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db import models

if TYPE_CHECKING:
    pass


class UUIDModel(models.Model):
    """Abstract base model that provides UUID primary key."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        db_index=True,
    )

    class Meta:
        abstract = True
        ordering = ["-created_at"]


class TimeStampedModel(models.Model):
    """Abstract base model that provides timestamp fields."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]


class SoftDeleteModel(models.Model):
    """Abstract base model that provides soft delete functionality."""

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_deleted_by",
        verbose_name="Deleted by",
    )

    class Meta:
        abstract = True
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["is_deleted", "created_at"]),
        ]

    def soft_delete(self, deleted_by=None):
        """Mark the instance as deleted."""

        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = deleted_by
        self.save()

    def restore(self):
        """Restore a soft-deleted instance."""
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save()

    def delete(self, using=None, keep_parents=False):
        """Override delete to use soft delete by default."""
        if self.is_deleted:
            return super().delete(using=using, keep_parents=keep_parents)
        self.soft_delete()

    def hard_delete(self, using=None):
        """Permanently delete the instance from database."""
        return super().delete(using=using)


class TenantModel(models.Model):
    """Abstract base model for multi-tenancy support.

    This model should be inherited by any domain-specific model that
    belongs to a store/tenant. It provides automatic filtering by store
    and ensures data isolation.
    """

    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_set",
        verbose_name="Store",
        db_index=True,
    )

    class Meta:
        abstract = True
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["store", "created_at"]),
        ]

    @classmethod
    def get_queryset_for_store(cls, store_id):
        """Get queryset filtered by store ID."""
        return cls.objects.filter(store_id=store_id)


class BaseModel(UUIDModel, TimeStampedModel, SoftDeleteModel):
    """Comprehensive base model combining all base model features."""

    class Meta:
        abstract = True
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["is_deleted", "created_at"]),
        ]


class TenantBaseModel(UUIDModel, TimeStampedModel, SoftDeleteModel, TenantModel):
    """Comprehensive base model for tenant-owned resources."""

    class Meta:
        abstract = True
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["is_deleted", "created_at"]),
            models.Index(fields=["store", "created_at"]),
        ]


class QuerySetModel(models.Model):
    """Abstract model with custom queryset support."""

    objects = models.Manager()

    class Meta:
        abstract = True


class StatusModel(models.Model):
    """Abstract model with status field."""

    STATUS_CHOICES = (
        ("active", "Active"),
        ("inactive", "Inactive"),
        ("pending", "Pending"),
        ("archived", "Archived"),
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="active",
        db_index=True,
    )

    class Meta:
        abstract = True
        ordering = ["-created_at"]
