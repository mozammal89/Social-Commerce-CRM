"""
Views for Store management.
"""

from django.db import models
from rest_framework import generics, status, permissions, exceptions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.stores.models import Store
from apps.stores.serializers import (
    StoreSerializer,
    StoreCreateSerializer,
    StoreUpdateSerializer,
    StoreStaffSerializer,
)
from apps.accounts.models import User


class StoreListView(generics.ListCreateAPIView):
    """View for listing and creating stores."""

    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Return stores accessible to current user."""
        user = self.request.user
        return Store.objects.filter(
            models.Q(owners=user) | models.Q(managers=user) | models.Q(staff=user)
        ).distinct()

    def get_serializer_class(self):
        """Return appropriate serializer based on request method."""
        if self.request.method == "POST":
            return StoreCreateSerializer
        return StoreSerializer

    def perform_create(self, serializer):
        """Save store with current user as owner."""
        serializer.save()


class StoreDetailView(generics.RetrieveUpdateDestroyAPIView):
    """View for retrieving, updating, and deleting stores."""

    serializer_class = StoreUpdateSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "id"

    def get_queryset(self):
        """Return stores accessible to current user."""
        user = self.request.user
        return Store.objects.filter(
            models.Q(owners=user) | models.Q(managers=user) | models.Q(staff=user)
        ).distinct()

    def get_serializer_class(self):
        """Return appropriate serializer based on request method."""
        if self.request.method == "GET":
            return StoreSerializer
        return StoreUpdateSerializer

    def perform_update(self, serializer):
        """Update store with validation."""
        store = self.get_object()
        user = self.request.user

        if not store.is_owner(user):
            raise exceptions.PermissionDenied("Only store owners can update store information.")

        serializer.save()

    def perform_destroy(self, instance):
        """Soft delete store."""
        user = self.request.user

        if not instance.is_owner(user):
            raise exceptions.PermissionDenied("Only store owners can delete stores.")

        instance.soft_delete(deleted_by=user)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def manage_store_staff(request, store_id):
    """View for managing store staff."""

    try:
        store = Store.objects.get(id=store_id)
    except Store.DoesNotExist:
        return Response({"error": "Store not found"}, status=status.HTTP_404_NOT_FOUND)

    if not store.is_owner(request.user):
        raise exceptions.PermissionDenied("Only store owners can manage staff.")

    serializer = StoreStaffSerializer(data=request.data, context={"store": store})
    serializer.is_valid(raise_exception=True)

    user_id = serializer.validated_data["user_id"]
    role = serializer.validated_data["role"]

    user = User.objects.get(id=user_id)

    if serializer.validated_data["action"] == "add":
        if role == "manager":
            store.add_manager(user)
        else:
            store.add_staff(user)
        message = f"User added as {role}"
    else:
        if role == "manager":
            store.remove_manager(user)
        else:
            store.remove_staff(user)
        message = f"User removed as {role}"

    return Response({"message": message}, status=status.HTTP_200_OK)


class MyStoresView(generics.ListAPIView):
    """View for listing current user's stores."""

    serializer_class = StoreSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Return stores owned by current user."""
        return Store.objects.by_owner(self.request.user.id)
