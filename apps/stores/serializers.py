"""
Serializers for Store model.
"""

from rest_framework import serializers
from apps.stores.models import Store
from apps.accounts.serializers import UserSerializer


class StoreSerializer(serializers.ModelSerializer):
    """Serializer for Store model."""

    owners = UserSerializer(many=True, read_only=True)
    managers = UserSerializer(many=True, read_only=True)
    staff = UserSerializer(many=True, read_only=True)
    owner_count = serializers.SerializerMethodField()
    manager_count = serializers.SerializerMethodField()
    staff_count = serializers.SerializerMethodField()

    class Meta:
        model = Store
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "logo",
            "status",
            "owners",
            "managers",
            "staff",
            "owner_count",
            "manager_count",
            "staff_count",
            "settings",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "slug",
            "created_at",
            "updated_at",
        ]

    def get_owner_count(self, obj):
        """Return count of store owners."""
        return obj.owners.count()

    def get_manager_count(self, obj):
        """Return count of store managers."""
        return obj.managers.count()

    def get_staff_count(self, obj):
        """Return count of store staff."""
        return obj.staff.count()


class StoreCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating stores."""

    class Meta:
        model = Store
        fields = [
            "name",
            "description",
            "logo",
            "settings",
        ]

    def create(self, validated_data):
        """Create a new store under the user's existing tenant + subscription.

        Bug history: this method used to create a brand-new store-level
        ``Subscription`` whenever ``pending_plan_slug`` was set, ignoring
        any subscription the user already had for another store. That
        left multi-store tenants with one sub per store, each carrying
        its own (stale) plan — Store A would report the Free cap while
        Store B reported the Growth cap. The fix is to honour the
        tenant/one-sub-per-tenant contract from the very first store:
        attach the new store to the user's tenant and, if
        ``pending_plan_slug`` is set, *upgrade the existing
        subscription* rather than create a duplicate store-level sub.
        """
        from django.db import transaction

        from apps.permissions.services import add_member
        from apps.permissions.models import Role
        from apps.subscriptions.services import (
            apply_pending_plan,
            get_or_create_default_tenant,
        )

        request = self.context["request"]
        user = request.user

        with transaction.atomic():
            tenant = get_or_create_default_tenant(user)

            # Bind the new store to the tenant. Without this, two stores
            # in the same workspace end up with independent caps.
            validated_data["tenant"] = tenant
            store = Store.objects.create(**validated_data)

            owner_role = Role.objects.get(slug="store-owner", store=None)
            add_member(user, store, owner_role)

            # ``apply_pending_plan`` upgrades the existing sub (or
            # creates the first one) and clears the pending marker.
            # No separate duplicate sub gets created for new stores
            # under an existing tenant.
            apply_pending_plan(user, store=store, request=request)

        return store


class StoreUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating stores."""

    class Meta:
        model = Store
        fields = [
            "name",
            "description",
            "logo",
            "status",
            "settings",
        ]


class StoreStaffSerializer(serializers.Serializer):
    """Serializer for managing store staff."""

    action = serializers.ChoiceField(choices=["add", "remove"])
    user_id = serializers.UUIDField()
    role = serializers.ChoiceField(choices=["manager", "staff"])

    def validate_user_id(self, value):
        """Validate that user exists."""
        from apps.accounts.models import User

        try:
            User.objects.get(id=value)
            return value
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found.")

    def validate(self, attrs):
        """Validate store access.

        Bug 8: this now consults ``StoreMembership`` (active rows) instead
        of the legacy ``Store.owners/managers/staff`` M2M, matching the
        write path in ``manage_store_staff``.
        """
        store = self.context["store"]
        user_id = attrs["user_id"]

        from apps.accounts.models import User
        from apps.permissions.models import StoreMembership

        user = User.objects.get(id=user_id)

        active = StoreMembership.objects.filter(
            user=user, store=store, is_active=True,
        )
        owner_role = store.owners.filter(id=user_id).exists()

        if attrs["action"] == "add":
            if owner_role:
                raise serializers.ValidationError("User is already an owner.")
            if active.filter(role__slug="manager").exists():
                raise serializers.ValidationError("User is already a manager.")
            if active.filter(role__slug="viewer").exists():
                raise serializers.ValidationError("User is already a staff member.")
        elif attrs["action"] == "remove":
            if owner_role:
                raise serializers.ValidationError(
                    "Cannot remove store owners via this endpoint.",
                )

        return attrs
