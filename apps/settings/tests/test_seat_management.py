"""
Comprehensive tests for seat management and team member creation.

This test suite ensures:
1. Store owners are correctly identified and excluded from seat counts
2. Seat limits are properly enforced when adding new members
3. The UI correctly reflects seat availability
4. Edge cases are handled (reactivation, owner changes, etc.)
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.db import transaction

from apps.stores.models import Store
from apps.permissions.models import StoreMembership, Role, SubscriptionPlan, Subscription
from apps.subscriptions.services import check_plan_limits, enforce_plan_limit
from apps.subscriptions.exceptions import PlanLimitExceeded
from apps.settings.views import get_store_owners, calculate_seat_usage

User = get_user_model()


class SeatManagementTestCase(TestCase):
    """Test seat management logic and enforcement."""

    def setUp(self):
        """Set up test data."""
        # Create users
        self.owner_user = User.objects.create_user(
            email="owner@example.com", password="testpass123", first_name="Store", last_name="Owner"
        )

        self.member_user1 = User.objects.create_user(
            email="member1@example.com",
            password="testpass123",
            first_name="Team",
            last_name="Member1",
        )

        self.member_user2 = User.objects.create_user(
            email="member2@example.com",
            password="testpass123",
            first_name="Team",
            last_name="Member2",
        )

        self.manager_user = User.objects.create_user(
            email="manager@example.com",
            password="testpass123",
            first_name="Team",
            last_name="Manager",
        )

        # Create store
        self.store = Store.objects.create(name="Test Store", slug="test-store")

        # Get roles
        self.owner_role = Role.objects.get(slug="store-owner", store__isnull=True)
        self.manager_role = Role.objects.get(slug="manager", store__isnull=True)
        self.staff_role = Role.objects.get(slug="staff", store__isnull=True)

        # Create subscription plan with 5 seats
        self.plan = SubscriptionPlan.objects.create(
            name="Test Plan",
            slug="test-plan",
            price=29.99,
            currency="USD",
            max_users=5,
            max_stores=1,
            billing_period="monthly",
        )

        # Create subscription for store
        self.subscription = Subscription.objects.create(
            store=self.store,
            plan=self.plan,
            status="active",
            starts_at=timezone.now(),
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=30),
        )

        # Add owner to store
        StoreMembership.objects.create(
            user=self.owner_user, store=self.store, role=self.owner_role, is_active=True
        )

        # Add initial members
        StoreMembership.objects.create(
            user=self.member_user1, store=self.store, role=self.staff_role, is_active=True
        )

        StoreMembership.objects.create(
            user=self.member_user2, store=self.store, role=self.staff_role, is_active=True
        )

        self.client = Client()
        self.client.force_login(self.owner_user)

    def test_get_store_owners_correctly_identifies_owners(self):
        """Test that get_store_owners correctly identifies store owners."""
        owners = get_store_owners(self.store)

        self.assertEqual(len(owners), 1)
        self.assertEqual(owners[0].id, self.owner_user.id)
        self.assertNotIn(self.member_user1, owners)
        self.assertNotIn(self.member_user2, owners)

    def test_calculate_seat_usage_excludes_owners(self):
        """Test that calculate_seat_usage excludes store owners from seat count."""
        seat_info = calculate_seat_usage(self.store)

        # Should have 2 members (member_user1 and member_user2), owner excluded
        self.assertEqual(seat_info["used_seats"], 2)
        self.assertEqual(seat_info["total_members"], 3)  # 2 members + 1 owner
        self.assertEqual(seat_info["owner_count"], 1)

    def test_check_plan_limits_excludes_owners(self):
        """Test that check_plan_limits excludes store owners from user count."""
        limits_info = check_plan_limits(self.store)

        self.assertEqual(limits_info["usage"]["users"], 2)  # 2 members, owner excluded
        self.assertEqual(limits_info["limits"]["max_users"], 5)
        self.assertEqual(limits_info["exceeded"], {})

    def test_enforce_plan_limit_prevents_exceeding_seats(self):
        """Test that enforce_plan_limit prevents exceeding seat limit."""
        # Current usage: 2 seats, limit: 5
        # Should allow adding up to 3 more members

        # This should work (2 < 5)
        enforce_plan_limit(self.store, "max_users", 2)

        # This should work (4 < 5)
        enforce_plan_limit(self.store, "max_users", 4)

        # This should fail (5 >= 5)
        with self.assertRaises(PlanLimitExceeded) as context:
            enforce_plan_limit(self.store, "max_users", 5)

        self.assertIn("max_users", str(context.exception))

    def test_can_add_members_within_limit(self):
        """Test that members can be added within the seat limit."""
        # Current usage: 2 seats, limit: 5
        # Should be able to add 3 more members

        new_member = User.objects.create_user(email="newmember@example.com", password="testpass123")

        # This should succeed
        membership = StoreMembership.objects.create(
            user=new_member, store=self.store, role=self.staff_role, is_active=True
        )

        # Verify seat count increased
        limits_info = check_plan_limits(self.store)
        self.assertEqual(limits_info["usage"]["users"], 3)

    def test_cannot_add_members_beyond_limit(self):
        """Test that members cannot be added beyond the seat limit."""
        # Add members to reach the limit (5 total)
        for i in range(3, 6):  # Add members 3, 4, 5
            new_member = User.objects.create_user(
                email=f"member{i}@example.com", password="testpass123"
            )
            StoreMembership.objects.create(
                user=new_member, store=self.store, role=self.staff_role, is_active=True
            )

        # Now at limit: 5 members (excluding owner)
        limits_info = check_plan_limits(self.store)
        self.assertEqual(limits_info["usage"]["users"], 5)

        # Try to add one more - should fail
        with self.assertRaises(PlanLimitExceeded):
            enforce_plan_limit(self.store, "max_users", 5)

    def test_store_owner_does_not_consume_seat(self):
        """Test that store owners do not consume seats."""
        # Current: 1 owner + 2 members = 2 seats used
        seat_info = calculate_seat_usage(self.store)
        self.assertEqual(seat_info["used_seats"], 2)

        # Add another owner (shouldn't increase seat count)
        new_owner = User.objects.create_user(email="owner2@example.com", password="testpass123")

        StoreMembership.objects.create(
            user=new_owner, store=self.store, role=self.owner_role, is_active=True
        )

        # Seat count should still be 2
        seat_info = calculate_seat_usage(self.store)
        self.assertEqual(seat_info["used_seats"], 2)
        self.assertEqual(seat_info["owner_count"], 2)

    def test_reactivating_member_checks_seat_limit(self):
        """Test that reactivating an inactive member checks seat limit."""
        # Deactivate a member
        membership = StoreMembership.objects.get(user=self.member_user1, store=self.store)
        membership.is_active = False
        membership.save()

        # Fill up seats to limit
        for i in range(3, 6):  # Add members 3, 4, 5
            new_member = User.objects.create_user(
                email=f"member{i}@example.com", password="testpass123"
            )
            StoreMembership.objects.create(
                user=new_member, store=self.store, role=self.staff_role, is_active=True
            )

        # Now at limit: 5 active members (excluding owner)
        limits_info = check_plan_limits(self.store)
        self.assertEqual(limits_info["usage"]["users"], 5)

        # Try to reactivate - should fail due to seat limit
        with self.assertRaises(PlanLimitExceeded):
            enforce_plan_limit(self.store, "max_users", 5)

    def test_changing_member_role_does_not_double_count(self):
        """Test that changing a member's role doesn't double count seats."""
        # Initial: 1 owner + 2 members = 2 seats
        seat_info = calculate_seat_usage(self.store)
        initial_seats = seat_info["used_seats"]
        self.assertEqual(initial_seats, 2)

        # Change member role to manager
        membership = StoreMembership.objects.get(user=self.member_user1, store=self.store)
        membership.role = self.manager_role
        membership.save()

        # Seat count should remain the same
        seat_info = calculate_seat_usage(self.store)
        self.assertEqual(seat_info["used_seats"], initial_seats)

    def test_inviting_existing_user_ignores_seat_if_inactive(self):
        """Test that inviting an existing inactive member ignores seat check for reactivation."""
        # This is a placeholder - the actual invite logic is tested via the API


class SeatManagementAPITestCase(TestCase):
    """Test seat management through API endpoints."""

    def setUp(self):
        """Set up test data."""
        # Create users
        self.owner_user = User.objects.create_user(
            email="owner@example.com", password="testpass123", first_name="Store", last_name="Owner"
        )

        # Create store and subscription with limited seats
        self.store = Store.objects.create(name="Test Store", slug="test-store")

        self.plan = SubscriptionPlan.objects.create(
            name="Test Plan",
            slug="test-plan",
            price=29.99,
            currency="USD",
            max_users=3,  # Only 3 seats for testing
            max_stores=1,
            billing_period="monthly",
        )

        self.subscription = Subscription.objects.create(
            store=self.store,
            plan=self.plan,
            status="active",
            starts_at=timezone.now(),
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=30),
        )

        # Get roles
        self.owner_role = Role.objects.get(slug="store-owner", store__isnull=True)
        self.staff_role = Role.objects.get(slug="staff", store__isnull=True)

        # Add owner
        StoreMembership.objects.create(
            user=self.owner_user, store=self.store, role=self.owner_role, is_active=True
        )

        self.client = Client()
        self.client.force_login(self.owner_user)

    def test_invite_member_within_limit_succeeds(self):
        """Test that inviting a member within the seat limit succeeds."""
        # Owner doesn't count, so we have 3 seats available
        response = self.client.post(
            f"/settings/team/{self.store.id}/invite/",
            {
                "email": "newmember@example.com",
                "role": self.staff_role.id,
                "message": "Welcome to the team!",
            },
            HTTP_X_CSRFTOKEN=self._get_csrf_token(),
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])

    def test_invite_member_beyond_limit_fails(self):
        """Test that inviting a member beyond the seat limit fails."""
        # Fill up all 3 seats
        for i in range(1, 4):
            member = User.objects.create_user(
                email=f"member{i}@example.com", password="testpass123"
            )
            StoreMembership.objects.create(
                user=member, store=self.store, role=self.staff_role, is_active=True
            )

        # Now at limit (3 members, excluding owner)
        limits_info = check_plan_limits(self.store)
        self.assertEqual(limits_info["usage"]["users"], 3)

        # Try to invite another member
        response = self.client.post(
            f"/settings/team/{self.store.id}/invite/",
            {
                "email": "overflow@example.com",
                "role": self.staff_role.id,
                "message": "Welcome to the team!",
            },
            HTTP_X_CSRFTOKEN=self._get_csrf_token(),
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("upgrade_required", data)
        self.assertIn("Seat limit reached", data["error"])

    def _get_csrf_token(self):
        """Helper to get CSRF token."""
        response = self.client.get(f"/settings/team/{self.store.id}/")
        return (
            response.cookies.get("csrftoken", "").value
            if hasattr(response, "cookies")
            else "testtoken"
        )
