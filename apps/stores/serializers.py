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
        """Create and return a new store."""
        user = self.context["request"].user
        store = Store.objects.create(**validated_data)
        store.add_owner(user)
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
