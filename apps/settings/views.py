"""
Settings views for store management including team management.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Q, Count

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


@login_required
@current_store
def team_management(request, store_id):
    """Team management page."""
    store = request.store

    if not store:
        messages.error(request, "Store not found")
        return redirect("stores:store_list_html")

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

    # Get team stats (including all members, excluding owners from seat count)
    total_members = StoreMembership.objects.filter(store=store).count()
    active_members = StoreMembership.objects.filter(store=store, is_active=True).count()
    available_roles = roles.filter(is_active=True).count()

    # Calculate seat usage (excluding owners)
    used_seats = (
        StoreMembership.objects.filter(store=store, is_active=True)
        .exclude(user__in=store.owners.all())
        .count()
    )

    # Get seat cap from subscription
    remaining_seats = None
    max_seats = None
    try:
        from apps.subscriptions.services import get_active_subscription

        subscription = get_active_subscription(store)
        if subscription and subscription.plan.max_users:
            max_seats = subscription.plan.max_users
            remaining_seats = max(0, max_seats - used_seats)
    except Exception:
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
        new_role = Role.objects.get(id=new_role_id, store=request.store)
        change_member_role_service(
            actor=request.user,
            membership=membership,
            new_role=new_role,
            request=request,
        )
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
        from django.core.validators import validate_email

        validate_email(email)
    except Exception:
        return JsonResponse({"success": False, "error": "Invalid email address"}, status=400)

    try:
        role = Role.objects.get(id=role_id, store=request.store)
    except Role.DoesNotExist:
        return JsonResponse({"success": False, "error": "Invalid role"}, status=400)

    from django.contrib.auth import get_user_model

    User = get_user_model()

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
                # Reactivate existing membership - check seat cap
                current_seats = (
                    StoreMembership.objects.filter(
                        store=request.store,
                        is_active=True,
                    )
                    .exclude(user__in=request.store.owners.all())
                    .count()
                )

                try:
                    from apps.subscriptions.services import enforce_plan_limit

                    enforce_plan_limit(request.store, "max_users", current_seats)
                except Exception as e:
                    return JsonResponse({"success": False, "error": str(e)}, status=400)

                existing_membership.is_active = True
                existing_membership.role = role
                existing_membership.save(update_fields=["is_active", "role", "updated_at"])

                AuditLog.objects.create(
                    action="member.reinvited",
                    actor=request.user,
                    target_type="StoreMembership",
                    target_id=str(existing_membership.id),
                    store=request.store,
                    metadata={
                        "user": email,
                        "role": role.name,
                    },
                )

                return JsonResponse(
                    {"success": True, "message": f"{email} has been reinvited to the team"}
                )
    except User.DoesNotExist:
        pass

    try:
        # Check seat cap before creating new user
        current_seats = (
            StoreMembership.objects.filter(
                store=request.store,
                is_active=True,
            )
            .exclude(user__in=request.store.owners.all())
            .count()
        )

        try:
            from apps.subscriptions.services import enforce_plan_limit

            enforce_plan_limit(request.store, "max_users", current_seats)
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=400)

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
            metadata={
                "user": email,
                "role": role.name,
                "message": message,
            },
        )

        # TODO: Send invitation email with token
        # This would typically involve creating an invitation token and sending an email

        return JsonResponse({"success": True, "message": f"Invitation sent to {email}"})
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


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
            metadata={
                "user": membership.user.email,
                "previous_role": membership.role.name,
            },
        )

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
            metadata={
                "user": membership.user.email,
                "current_role": membership.role.name,
            },
        )

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
                metadata={
                    "user": user_email,
                    "removed_role": membership.role.name,
                },
            )
            membership.delete()

        return JsonResponse(
            {"success": True, "message": f"{user_email} has been removed from the team"}
        )
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
        from django.core.validators import validate_email

        validate_email(email)
    except Exception:
        return JsonResponse({"success": False, "error": "Invalid email address"}, status=400)

    try:
        role = Role.objects.get(id=role_id, store=request.store)
    except Role.DoesNotExist:
        return JsonResponse({"success": False, "error": "Invalid role"}, status=400)

    from django.contrib.auth import get_user_model

    User = get_user_model()

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
                # Reactivate existing membership
                existing_membership.is_active = True
                existing_membership.role = role
                existing_membership.save(update_fields=["is_active", "role", "updated_at"])

                AuditLog.objects.create(
                    action="member.reinvited",
                    actor=request.user,
                    target_type="StoreMembership",
                    target_id=str(existing_membership.id),
                    store=request.store,
                    metadata={
                        "user": email,
                        "role": role.name,
                    },
                )

                return JsonResponse(
                    {"success": True, "message": f"{email} has been reinvited to the team"}
                )
    except User.DoesNotExist:
        pass

    try:
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
            metadata={
                "user": email,
                "role": role.name,
                "message": message,
            },
        )

        # TODO: Send invitation email with token
        # This would typically involve creating an invitation token and sending an email

        return JsonResponse({"success": True, "message": f"Invitation sent to {email}"})
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
