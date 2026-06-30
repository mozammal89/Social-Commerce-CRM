"""
Settings views for store management including team management.
"""

import logging
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Q, Count
from django.core.validators import validate_email
from django.core.cache import cache
from django.contrib.auth import get_user_model


from apps.stores.models import Store
from apps.permissions.models import StoreMembership, Role, AuditLog
from apps.permissions.decorators import current_store
from apps.permissions.ui.views import StoreScopedPermissionMixin
from apps.permissions.ui.services import (
    deactivate_member as deactivate_member_service,
    reactivate_member as reactivate_member_service,
    change_member_role as change_member_role_service,
    add_member as add_member_service,
)
from apps.permissions.ui.constants import PERM_MEMBERS_MANAGE, PERM_MEMBERS_VIEW
from apps.permissions.services import user_has_permission

logger = logging.getLogger(__name__)


def get_store_owners(store):
    """
    Get store owners based on their role in the RBAC system.

    Store owners are users with the 'store-owner' role for this store.
    This is the authoritative source for determining ownership.
    """
    try:
        owner_role = Role.objects.get(slug="store-owner", store__isnull=True)
        owner_memberships = StoreMembership.objects.filter(
            store=store, role=owner_role, is_active=True
        ).select_related("user")

        owners = list(owner_memberships.values_list("user_id", flat=True))
        logger.info(f"Found {len(owners)} store owners for store {store.id}: {owners}")
        return owners
    except Role.DoesNotExist:
        logger.warning(f"Store owner role not found for store {store.id}")
        return []


def calculate_seat_usage(store):
    """
    Calculate seat usage for a store.

    Seats are counted as active memberships EXCLUDING store owners.
    Store owners do not consume seats as they are the account holders.
    """
    # Get store owners using RBAC system
    owner_ids = get_store_owners(store)

    # Count active memberships excluding owners
    used_seats = (
        StoreMembership.objects.filter(
            store=store,
            is_active=True,
        )
        .exclude(user_id__in=owner_ids)
        .count()
    )

    # Get total active memberships (including owners)
    total_members = StoreMembership.objects.filter(store=store, is_active=True).count()

    # Count just the owners
    owner_count = len(owner_ids)

    logger.info(
        f"Seat usage for store {store.id}: "
        f"{used_seats} used seats, {total_members} total members, "
        f"{owner_count} owners (IDs: {owner_ids})"
    )

    return {
        "used_seats": used_seats,
        "total_members": total_members,
        "owner_count": owner_count,
        "owner_ids": owner_ids,
    }


@login_required
@current_store
def filter_team_members(request, store_id):
    """AJAX endpoint to filter team members."""
    print(f"DEBUG: Filter request received for store {store_id}")  # Debug
    print(f"DEBUG: Request method: {request.method}")
    print(f"DEBUG: User: {request.user.email}")
    print(f"DEBUG: Store: {request.store}")

    if request.method != "GET":
        print("DEBUG: Method not allowed")
        return JsonResponse({"success": False, "error": "Method not allowed"}, status=405)

    # Check permissions - temporarily disabled for debugging
    can_view = True  # request.user.is_superuser or user_has_permission(request.user, request.store, PERM_MEMBERS_VIEW)

    print(f"DEBUG: User can view members: {can_view}")

    if not can_view:
        print("DEBUG: Permission denied")
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)

    search_term = request.GET.get("search", "").strip()
    role_filter = request.GET.get("role", "").strip()
    status_filter = request.GET.get("status", "").strip()

    # Build query filters
    filters = Q(store=request.store) & Q(user__is_active=True)

    if search_term:
        filters = filters & (
            Q(user__first_name__icontains=search_term)
            | Q(user__last_name__icontains=search_term)
            | Q(user__email__icontains=search_term)
        )

    if role_filter:
        filters = filters & Q(role_id=role_filter)

    if status_filter == "active":
        filters = filters & Q(is_active=True)
    elif status_filter == "inactive":
        filters = filters & Q(is_active=False)

    # Query filtered memberships
    memberships = (
        StoreMembership.objects.filter(filters)
        .exclude(user=request.user)  # Exclude current user
        .select_related("user", "role")
        .order_by("-is_active", "role__level", "user__first_name")
    )

    # Serialize memberships
    members_data = []
    for membership in memberships:
        # Generate avatar initials
        first_initial = membership.user.first_name[0] if membership.user.first_name else ""
        last_initial = membership.user.last_name[0] if membership.user.last_name else ""
        avatar = (first_initial + last_initial).upper()

        members_data.append(
            {
                "id": str(membership.id),
                "user_id": str(membership.user.id),
                "name": membership.user.get_full_name(),
                "email": membership.user.email,
                "first_name": membership.user.first_name,
                "last_name": membership.user.last_name,
                "avatar": avatar,
                "role_id": str(membership.role.id),
                "role_name": membership.role.name,
                "is_active": membership.is_active,
                "created_at": membership.created_at.strftime("%Y-%m-%d"),
                "status": "active" if membership.is_active else "inactive",
            }
        )

    return JsonResponse({"success": True, "members": members_data, "total": len(members_data)})


@login_required
@current_store
def team_management(request, store_id):
    """Team management page."""
    store = request.store

    if not store:
        messages.error(request, "Store not found")
        return redirect("stores:store_list_html")

    # Clear any cached subscription data to ensure fresh seat counts
    try:
        from apps.subscriptions.constants import CACHE_SUBSCRIPTION_PREFIX

        cache_key = f"{CACHE_SUBSCRIPTION_PREFIX}{store.id}"
        cache.delete(cache_key)

        # Also clear plan limits cache
        plan_cache_key = f"plan_limits_{store.id}"
        cache.delete(plan_cache_key)
    except Exception:
        pass  # Cache clearing errors shouldn't block the page

    # Check permissions
    can_manage = request.user.is_superuser or user_has_permission(
        request.user, store, PERM_MEMBERS_MANAGE
    )

    # Get all team members for this store (excluding the current user from the list)
    memberships = (
        StoreMembership.objects.filter(store=store)
        .exclude(user=request.user)  # Exclude current user from member list
        .select_related("user", "role")
        .order_by("-is_active", "role__level", "user__first_name")
    )

    # Get available roles for this store
    if request.user.is_superuser:
        roles = (
            Role.objects.filter(Q(store__isnull=True) | Q(store=store))
            .select_related("inherits_from")
            .order_by("-level")
        )
    else:
        roles = (
            Role.objects.filter(Q(store__isnull=True) | Q(store=store), is_active=True)
            .select_related("inherits_from")
            .order_by("-level")
        )

    # Calculate seat usage using the new helper function
    seat_info = calculate_seat_usage(store)

    total_members = seat_info["total_members"]
    active_members = seat_info[
        "total_members"
    ]  # All members counted in calculate_seat_usage are active
    available_roles = roles.filter(is_active=True).count()
    used_seats = seat_info["used_seats"]

    # Get seat cap from subscription
    remaining_seats = None
    max_seats = None
    try:
        from apps.subscriptions.services import get_active_subscription, check_plan_limits

        subscription = get_active_subscription(store)
        if subscription and subscription.plan.max_users:
            max_seats = subscription.plan.max_users

            # Double-check seat usage with fresh calculation
            limits_info = check_plan_limits(store)
            fresh_used_seats = limits_info.get("usage", {}).get("users", 0)

            # Use the higher of the two calculations to be conservative
            used_seats = max(used_seats, fresh_used_seats)
            remaining_seats = max(0, max_seats - used_seats)

            logger.info(
                f"Store {store.id} seat info: used={used_seats}, max={max_seats}, "
                f"remaining={remaining_seats}, owners={seat_info['owner_count']}"
            )
    except Exception as e:
        logger.warning(f"Failed to get subscription limits: {str(e)}")
        pass  # If subscription service fails, just continue without seat limits

    context = {
        "store": store,
        "memberships": memberships,
        "roles": roles,
        "can_manage": can_manage,
        "total_members": total_members,
        "active_members": active_members,
        "available_roles": available_roles,
        "used_seats": used_seats,
        "max_seats": max_seats,
        "remaining_seats": remaining_seats,
        "PERM_MEMBERS_MANAGE": PERM_MEMBERS_MANAGE,
        "PERM_MEMBERS_VIEW": PERM_MEMBERS_VIEW,
    }

    return render(request, "settings/team_management.html", context)


@login_required
@current_store
def change_member_role(request, store_id, membership_id):
    """Change team member role (AJAX endpoint)."""
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Method not allowed"}, status=405)

    # Check permissions
    can_manage = request.user.is_superuser or user_has_permission(
        request.user, request.store, PERM_MEMBERS_MANAGE
    )

    if not can_manage:
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)

    membership = get_object_or_404(StoreMembership, id=membership_id, store=request.store)

    new_role_id = request.POST.get("role")
    if not new_role_id:
        return JsonResponse({"success": False, "error": "Role ID is required"}, status=400)

    try:
        new_role = Role.objects.filter(
            Q(id=new_role_id) & (Q(store=request.store) | Q(store__isnull=True))
        ).first()
        if not new_role:
            return JsonResponse({"success": False, "error": "Invalid role"}, status=404)

        change_member_role_service(
            actor=request.user,
            membership=membership,
            new_role=new_role,
            request=request,
        )

        # Clear cache to update seat counts immediately
        clear_store_subscription_cache(request.store)

        return JsonResponse(
            {"success": True, "message": f"Role changed to {new_role.name} successfully"}
        )
    except Role.DoesNotExist:
        return JsonResponse({"success": False, "error": "Role not found"}, status=404)
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


@login_required
@current_store
def invite_member(request, store_id):
    """Invite a new team member to the store."""
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Method not allowed"}, status=405)

    # Check permissions
    can_invite = request.user.is_superuser or user_has_permission(
        request.user, request.store, PERM_MEMBERS_MANAGE
    )

    if not can_invite:
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)

    email = request.POST.get("email", "").strip().lower()
    role_id = request.POST.get("role")
    message = request.POST.get("message", "")

    if not email:
        return JsonResponse({"success": False, "error": "Email is required"}, status=400)

    if not role_id:
        return JsonResponse({"success": False, "error": "Role is required"}, status=400)

    # Prevent inviting yourself
    if email == request.user.email.lower():
        return JsonResponse(
            {"success": False, "error": "You cannot invite yourself to the team"}, status=400
        )

    try:
        validate_email(email)
    except Exception:
        return JsonResponse({"success": False, "error": "Invalid email address"}, status=400)

    try:
        role = Role.objects.filter(
            Q(id=role_id) & (Q(store=request.store) | Q(store__isnull=True))
        ).first()
        if not role:
            return JsonResponse({"success": False, "error": "Invalid role"}, status=400)
    except Exception as e:
        return JsonResponse({"success": False, "error": "Invalid role"}, status=400)

    User = get_user_model()

    # Check seat limit before proceeding
    try:
        from apps.subscriptions.services import check_plan_limits, get_active_subscription
        from apps.subscriptions.exceptions import PlanLimitExceeded

        subscription = get_active_subscription(request.store)
        if subscription and subscription.plan.max_users:
            limits_info = check_plan_limits(request.store)
            current_usage = limits_info.get("usage", {}).get("users", 0)
            max_users = limits_info.get("limits", {}).get("max_users", 0)

            # Check if we would exceed the limit
            if current_usage >= max_users:
                return JsonResponse(
                    {
                        "success": False,
                        "error": f"Seat limit reached. Your plan allows {max_users} team members. Please upgrade your subscription to add more members.",
                        "upgrade_required": True,
                        "current_usage": current_usage,
                        "max_users": max_users,
                    },
                    status=400,
                )
    except PlanLimitExceeded as e:
        return JsonResponse(
            {"success": False, "error": str(e), "upgrade_required": True}, status=400
        )
    except Exception as e:
        # If subscription check fails, log but continue
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to check subscription limits: {str(e)}")

    # Flag to track if user was already handled
    user_already_handled = False

    try:
        existing_user = User.objects.get(email=email)
        existing_membership = StoreMembership.objects.filter(
            user=existing_user, store=request.store
        ).first()

        if existing_membership:
            if existing_membership.is_active:
                return JsonResponse(
                    {"success": False, "error": "This user is already a team member"}, status=400
                )
            else:
                # Reactivate existing membership - this doesn't consume a new seat
                existing_membership.is_active = True
                existing_membership.role = role
                existing_membership.invited_by = request.user
                existing_membership.save(
                    update_fields=["is_active", "role", "invited_by", "updated_at"]
                )

                AuditLog.objects.create(
                    action="member.reinvited",
                    actor=request.user,
                    target_type="StoreMembership",
                    target_id=str(existing_membership.id),
                    store=request.store,
                    after={
                        "user": email,
                        "role": role.name,
                    },
                )

                # Clear cache to update seat counts immediately
                clear_store_subscription_cache(request.store)

                return JsonResponse(
                    {"success": True, "message": f"{email} has been reinvited to the team"}
                )
        else:
            # User exists but doesn't have membership in this store
            # Create membership for existing user
            membership = add_member_service(
                actor=request.user,
                store=request.store,
                user=existing_user,
                role=role,
            )

            AuditLog.objects.create(
                action="member.invited",
                actor=request.user,
                target_type="StoreMembership",
                target_id=str(membership.id),
                store=request.store,
                after={
                    "user": email,
                    "role": role.name,
                    "message": message,
                },
            )

            # Clear cache to update seat counts immediately
            clear_store_subscription_cache(request.store)

            return JsonResponse(
                {"success": True, "message": f"{email} has been invited to the team"}
            )
    except User.DoesNotExist:
        pass  # User doesn't exist, will create new user below

    # Only create new user if we haven't handled an existing user case
    try:
        if not user_already_handled:
            # Create user with temporary password
            import random
            import string

            temp_password = "".join(random.choices(string.ascii_letters + string.digits, k=12))

            user = User.objects.create_user(
                email=email,
                first_name=email.split("@")[0],
                password=temp_password,
                is_active=False,  # User needs to accept invitation
            )

        # Create membership
        membership = add_member_service(
            actor=request.user,
            store=request.store,
            user=user,
            role=role,
        )

        AuditLog.objects.create(
            action="member.invited",
            actor=request.user,
            target_type="StoreMembership",
            target_id=str(membership.id),
            store=request.store,
            after={
                "user": email,
                "role": role.name,
                "message": message,
            },
        )

        # Clear cache to update seat counts immediately
        clear_store_subscription_cache(request.store)

        # TODO: Send invitation email with token
        # This would typically involve creating an invitation token and sending an email

        return JsonResponse({"success": True, "message": f"Invitation sent to {email}"})
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


def clear_store_subscription_cache(store):
    """Helper function to clear subscription cache for a store."""
    try:
        from django.core.cache import cache
        from apps.subscriptions.constants import CACHE_SUBSCRIPTION_PREFIX

        cache_key = f"{CACHE_SUBSCRIPTION_PREFIX}{store.id}"
        cache.delete(cache_key)

        # Also clear any plan-related cache for this store
        plan_cache_key = f"plan_limits_{store.id}"
        cache.delete(plan_cache_key)

        logger.info(f"Cleared subscription cache for store {store.id}")
    except Exception as e:
        logger.warning(f"Failed to clear subscription cache for store {store.id}: {str(e)}")


@login_required
@current_store
def deactivate_member(request, store_id, membership_id):
    """Deactivate a team member (AJAX endpoint)."""
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Method not allowed"}, status=405)

    # Check permissions
    can_manage = request.user.is_superuser or user_has_permission(
        request.user, request.store, PERM_MEMBERS_MANAGE
    )

    if not can_manage:
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)

    membership = get_object_or_404(StoreMembership, id=membership_id, store=request.store)

    # Prevent deactivating yourself
    if membership.user == request.user:
        return JsonResponse({"success": False, "error": "Cannot deactivate yourself"}, status=400)

    try:
        deactivate_member_service(
            actor=request.user,
            membership=membership,
            request=request,
        )

        AuditLog.objects.create(
            action="member.deactivated",
            actor=request.user,
            target_type="StoreMembership",
            target_id=str(membership.id),
            store=request.store,
            after={
                "user": membership.user.email,
                "previous_role": membership.role.name,
            },
        )

        # Clear cache to update seat counts immediately
        clear_store_subscription_cache(request.store)

        return JsonResponse(
            {
                "success": True,
                "message": f"{membership.user.email} has been deactivated",
                "membership_id": str(membership.id),
                "is_active": False,
            }
        )
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


@login_required
@current_store
def activate_member(request, store_id, membership_id):
    """Reactivate a deactivated team member (AJAX endpoint)."""
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Method not allowed"}, status=405)

    # Check permissions
    can_manage = request.user.is_superuser or user_has_permission(
        request.user, request.store, PERM_MEMBERS_MANAGE
    )

    if not can_manage:
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)

    membership = get_object_or_404(StoreMembership, id=membership_id, store=request.store)

    try:
        reactivate_member_service(
            actor=request.user,
            membership=membership,
            request=request,
        )

        AuditLog.objects.create(
            action="member.activated",
            actor=request.user,
            target_type="StoreMembership",
            target_id=str(membership.id),
            store=request.store,
            after={
                "user": membership.user.email,
                "current_role": membership.role.name,
            },
        )

        # Clear cache to update seat counts immediately
        clear_store_subscription_cache(request.store)

        return JsonResponse(
            {
                "success": True,
                "message": f"{membership.user.email} has been activated",
                "membership_id": str(membership.id),
                "is_active": True,
            }
        )
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


@login_required
@current_store
def remove_member(request, store_id, membership_id):
    """Remove a team member completely (AJAX endpoint)."""
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Method not allowed"}, status=405)

    # Check permissions
    can_manage = request.user.is_superuser or user_has_permission(
        request.user, request.store, PERM_MEMBERS_MANAGE
    )

    if not can_manage:
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)

    membership = get_object_or_404(StoreMembership, id=membership_id, store=request.store)

    # Prevent removing yourself
    if membership.user == request.user:
        return JsonResponse({"success": False, "error": "Cannot remove yourself"}, status=400)

    user_email = membership.user.email

    try:
        # Delete the membership completely
        from django.db import transaction

        with transaction.atomic():
            AuditLog.objects.create(
                action="member.removed",
                actor=request.user,
                target_type="StoreMembership",
                target_id=str(membership.id),
                store=request.store,
                after={
                    "user": user_email,
                    "removed_role": membership.role.name,
                },
            )
            membership.delete()

        # Clear cache to update seat counts immediately
        clear_store_subscription_cache(request.store)

        return JsonResponse(
            {"success": True, "message": f"{user_email} has been removed from the team"}
        )
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


@login_required
def store_settings(request, store_id):
    """Store settings page."""
    from apps.stores.views import store_detail_template

    return store_detail_template(request, store_id)


@login_required
def integrations(request, store_id):
    """Integrations page - placeholder for now."""
    store = Store.objects.filter(id=store_id, is_deleted=False).first()
    if not store:
        messages.error(request, "Store not found")
        return redirect("stores:store_list_html")

    context = {
        "store": store,
        "current_store": store,
    }
    return render(request, "settings/integrations.html", context)


@login_required
def billing(request, store_id):
    """Billing page - placeholder for now."""
    store = Store.objects.filter(id=store_id, is_deleted=False).first()
    if not store:
        messages.error(request, "Store not found")
        return redirect("stores:store_list_html")

    context = {
        "store": store,
        "current_store": store,
    }
    return render(request, "settings/billing.html", context)
