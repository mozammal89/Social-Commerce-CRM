"""
Comprehensive tests for seat management and team member creation.

This test suite ensures:
1. Store owners are correctly identified and excluded from seat counts
2. Seat limits are properly enforced when adding new members
3. The UI correctly reflects seat availability
4. Edge cases are handled (reactivation, owner changes, etc.)
"""

import pytest
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.db import transaction
from django.utils import timezone

from apps.stores.models import Store
from apps.permissions.models import StoreMembership, Role
from apps.subscriptions.models import SubscriptionPlan, Subscription
from apps.subscriptions.services import check_plan_limits, enforce_plan_limit
from apps.subscriptions.exceptions import PlanLimitExceeded
from apps.settings.views import get_store_owners, calculate_seat_usage

User = get_user_model()


class SeatManagementTestCase(TestCase):
    """Test seat management logic and enforcement."""

    def setUp(self):
        """Set up test data."""
        # Seed the global system roles that the rest of the setUp depends on.
        from apps.permissions.seeders.roles_seeder import RolesSeeder
        from apps.permissions.seeders.permissions_seeder import RolePermissionsSeeder
        from apps.permissions.seeders.resources_seeder import ResourcesSeeder

        ResourcesSeeder().run()
        RolesSeeder().run()
        RolePermissionsSeeder(verbosity=0).run()

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
        # No "staff" slug in the seeder; use "viewer" (lowest-privilege role
        # that any plan can grant) as the seat-consuming role for tests.
        self.staff_role = Role.objects.get(slug="viewer", store__isnull=True)

        # Create subscription plan with 5 seats
        self.plan = SubscriptionPlan.objects.create(
            name="Test Plan",
            slug="test-plan",
            price=29.99,
            currency="USD",
            max_users=5,
            # Generous max_stores so this plan can host any test store
            # without tripping the ``exceeded`` flag in check_plan_limits.
            max_stores=10,
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
        """Test that get_store_owners correctly identifies store owners.

        ``get_store_owners`` returns a list of user IDs (UUIDs).
        """
        owners = get_store_owners(self.store)

        self.assertEqual(len(owners), 1)
        self.assertEqual(owners[0], self.owner_user.id)
        self.assertNotIn(self.member_user1.id, owners)
        self.assertNotIn(self.member_user2.id, owners)

    def test_calculate_seat_usage_excludes_owners(self):
        """Test that calculate_seat_usage excludes store owners from seat count.

        Seats are counted as active + inactive non-owner memberships.
        This closes the deactivate/reactivate bypass.
        """
        seat_info = calculate_seat_usage(self.store)

        # Should have 2 members (member_user1 and member_user2), owner excluded
        self.assertEqual(seat_info["used_seats"], 2)
        self.assertEqual(seat_info["active_members"], 2)
        self.assertEqual(seat_info["owner_count"], 1)

    def test_check_plan_limits_excludes_owners(self):
        """Test that check_plan_limits excludes store owners from user count.

        The dict exposes ``reserved_users`` (active + inactive non-owner rows
        — what the seat-cap enforcement checks against) and ``users`` (active
        only — for UI display).
        """
        limits_info = check_plan_limits(self.store)

        self.assertEqual(limits_info["usage"]["users"], 2)  # 2 active
        self.assertEqual(limits_info["usage"]["reserved_users"], 2)
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

        self.assertIn("team members", str(context.exception))

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
        self.assertEqual(limits_info["usage"]["reserved_users"], 3)

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
        self.assertEqual(seat_info["active_members"], 2)

        # Add another owner (shouldn't increase seat count)
        new_owner = User.objects.create_user(email="owner2@example.com", password="testpass123")

        StoreMembership.objects.create(
            user=new_owner, store=self.store, role=self.owner_role, is_active=True
        )

        # Seat count should still be 2 (owners don't consume seats)
        seat_info = calculate_seat_usage(self.store)
        self.assertEqual(seat_info["used_seats"], 2)
        self.assertEqual(seat_info["owner_count"], 2)

    def test_reactivating_member_at_reserved_cap_succeeds(self):
        """Reactivating a row that's already counted in ``reserved_users``
        is safe — it doesn't change the reserved count.

        Bug-fix regression: reactivation must NOT block when
        ``reserved_users == max_users``. The seat row is already in
        the reserved count; flipping it active changes nothing.
        The cap bypass is prevented at the ``add_member`` write path
        which checks ``reserved + 1 > max`` before inserting a new
        row.
        """
        from apps.permissions.ui.services import reactivate_member

        # Deactivate a member
        membership = StoreMembership.objects.get(user=self.member_user1, store=self.store)
        membership.is_active = False
        membership.save()

        # Fill up seats to limit (5 reserved: 4 active + 1 inactive)
        for i in range(3, 6):  # Add members 3, 4, 5
            new_member = User.objects.create_user(
                email=f"member{i}@example.com", password="testpass123"
            )
            StoreMembership.objects.create(
                user=new_member, store=self.store, role=self.staff_role, is_active=True
            )

        # 5 reserved seats (4 active + 1 inactive), 4 active seats
        limits_info = check_plan_limits(self.store)
        self.assertEqual(limits_info["usage"]["users"], 4)  # active only
        self.assertEqual(limits_info["usage"]["reserved_users"], 5)
        self.assertEqual(limits_info["limits"]["max_users"], 5)

        # Reactivate the deactivated member → reserved stays 5, which
        # equals max_users. Reactivation is a no-op for the reserved
        # count, so it must succeed.
        result = reactivate_member(
            actor=self.owner_user,
            membership=membership,
        )
        self.assertTrue(result.is_active)

        # Reserved count is still 5.
        limits_info = check_plan_limits(self.store)
        self.assertEqual(limits_info["usage"]["reserved_users"], 5)

    def test_reactivating_member_blocks_only_when_cap_exceeded(self):
        """Reactivation is blocked only when ``reserved > max``.

        A reserved > max situation should be impossible in normal
        flow (add_member enforces the cap on insert), but if it ever
        occurs — e.g. legacy data, plan downgrade — reactivation
        must not silently allow further growth. We simulate it by
        inserting a row directly with is_active=False when the cap
        is already at max, pushing reserved to max+1.
        """
        from apps.permissions.ui.services import reactivate_member

        # Fill up to reserved == max (5).
        for i in range(3, 6):
            new_member = User.objects.create_user(
                email=f"member{i}@example.com", password="testpass123"
            )
            StoreMembership.objects.create(
                user=new_member, store=self.store, role=self.staff_role, is_active=True
            )

        # 5 reserved (5 active), max=5.
        limits_info = check_plan_limits(self.store)
        self.assertEqual(limits_info["usage"]["reserved_users"], 5)
        self.assertEqual(limits_info["limits"]["max_users"], 5)

        # Bypass add_member's seat check by inserting a 6th row directly
        # with is_active=False. This pushes reserved to 6, exceeding max.
        extra_user = User.objects.create_user(
            email="extra@example.com", password="testpass123"
        )
        extra_membership = StoreMembership.objects.create(
            user=extra_user, store=self.store, role=self.staff_role, is_active=False
        )

        limits_info = check_plan_limits(self.store)
        self.assertEqual(limits_info["usage"]["reserved_users"], 6)
        self.assertEqual(limits_info["usage"]["users"], 5)  # still 5 active

        # Reactivation must now be blocked because reserved > max.
        with self.assertRaises(PlanLimitExceeded):
            reactivate_member(actor=self.owner_user, membership=extra_membership)

        # The only path that frees a reserved seat is hard-delete.
        extra_membership.delete()
        limits_info = check_plan_limits(self.store)
        self.assertEqual(limits_info["usage"]["reserved_users"], 5)

    def test_add_member_blocks_when_reserved_at_cap(self):
        """``add_member`` enforces the cap using reserved_users (>= max).

        Regression: a tenant with reserved == max cannot insert a new
        row — even if some of those reserved rows are inactive. The
        only way to free a seat is hard-delete (remove_member).
        """
        from apps.permissions.ui.services import add_member

        # Fill up to reserved == max (5).
        for i in range(3, 6):
            new_member = User.objects.create_user(
                email=f"member{i}@example.com", password="testpass123"
            )
            StoreMembership.objects.create(
                user=new_member, store=self.store, role=self.staff_role, is_active=True
            )

        limits_info = check_plan_limits(self.store)
        self.assertEqual(limits_info["usage"]["reserved_users"], 5)

        # Now try to add a 6th member — must fail.
        overflow_user = User.objects.create_user(
            email="overflow@example.com", password="testpass123"
        )
        with self.assertRaises(PlanLimitExceeded):
            add_member(
                actor=self.owner_user,
                store=self.store,
                user=overflow_user,
                role=self.staff_role,
            )

        # Deactivate one — reserved still 5, active is 4. add_member
        # is STILL blocked because reserved >= max.
        active_memberships = StoreMembership.objects.filter(
            store=self.store, role=self.staff_role, is_active=True
        )[:1]
        for m in active_memberships:
            m.is_active = False
            m.save()

        limits_info = check_plan_limits(self.store)
        self.assertEqual(limits_info["usage"]["users"], 4)
        self.assertEqual(limits_info["usage"]["reserved_users"], 5)

        with self.assertRaises(PlanLimitExceeded):
            add_member(
                actor=self.owner_user,
                store=self.store,
                user=overflow_user,
                role=self.staff_role,
            )

        # Hard-delete one — reserved drops to 4. add_member succeeds.
        inactive = StoreMembership.objects.filter(
            store=self.store, role=self.staff_role, is_active=False
        ).first()
        inactive.delete()

        limits_info = check_plan_limits(self.store)
        self.assertEqual(limits_info["usage"]["reserved_users"], 4)

        result = add_member(
            actor=self.owner_user,
            store=self.store,
            user=overflow_user,
            role=self.staff_role,
        )
        self.assertTrue(result.is_active)

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
        """Re-invite of an existing inactive member is gated by reserved seats.

        Bug-fix regression: pre-fix, the invite_member view's "reinvite"
        branch flipped ``is_active=True`` without consulting the seat
        cap. Now it does, using the reserved-seat count. This test
        documents the post-fix contract via the API layer below; here we
        just make sure calculate_seat_usage correctly counts inactive
        rows.
        """
        membership = StoreMembership.objects.get(user=self.member_user1, store=self.store)
        membership.is_active = False
        membership.save()

        seat_info = calculate_seat_usage(self.store)
        # member_user1 is inactive but still occupies its seat.
        self.assertEqual(seat_info["used_seats"], 2)
        self.assertEqual(seat_info["active_members"], 1)


class SeatManagementAPITestCase(TestCase):
    """Test seat management through API endpoints."""

    def setUp(self):
        """Set up test data."""
        # Seed the global system roles that the rest of the setUp depends on.
        from apps.permissions.seeders.roles_seeder import RolesSeeder
        from apps.permissions.seeders.permissions_seeder import RolePermissionsSeeder
        from apps.permissions.seeders.resources_seeder import ResourcesSeeder

        ResourcesSeeder().run()
        RolesSeeder().run()
        RolePermissionsSeeder(verbosity=0).run()

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
            max_stores=10,
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
        # No "staff" slug in the seeder; use "viewer" as the seat-consuming role.
        self.staff_role = Role.objects.get(slug="viewer", store__isnull=True)

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
        self.assertTrue(data["upgrade_required"])
        self.assertEqual(data["limit_type"], "max_users")
        self.assertEqual(data["limit_value"], 3)
        # New member would push reserved count from 3 → 4.
        self.assertEqual(data["current_usage"], 4)
        self.assertIn("team members", data["error"].lower())

    def _get_csrf_token(self):
        """Helper to get CSRF token."""
        response = self.client.get(f"/settings/team/{self.store.id}/")
        return (
            response.cookies.get("csrftoken", "").value
            if hasattr(response, "cookies")
            else "testtoken"
        )
