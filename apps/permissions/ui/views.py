"""
Views for the role/permission management UI.

Four groups of pages:
  1. Role list, create, edit, delete, clone
  2. Member list, invite, change role, deactivate
  3. Audit log viewer (read-only)
  4. AJAX endpoints for permission toggling and member actions

All views use the mixins in ``apps.permissions.ui.mixins`` to enforce
super-admin vs store-admin access. Mutations go through
``apps.permissions.ui.services``.
"""

from __future__ import annotations

import json
from typing import Any

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
)

from apps.permissions.models import (
    AuditLog,
    Permission,
    Resource,
    Role,
    StoreMembership,
    UserPermissionOverride,
)
from apps.permissions.services import user_has_permission
from apps.stores.models import Store

from .constants import (
    PERM_AUDIT_VIEW,
    PERM_MEMBERS_MANAGE,
    PERM_MEMBERS_VIEW,
    PERM_PERMISSIONS_OVERRIDE,
    PERM_PERMISSIONS_VIEW,
    PERM_ROLES_MANAGE,
    PERM_ROLES_VIEW,
)
from .forms import MembershipForm, RoleCloneForm, RoleForm, UserOverrideForm
from .mixins import (
    StoreScopedPermissionMixin,
    SuperuserOnlyMixin,
    get_user_stores_for_admin,
)
from . import services

User = get_user_model()


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class RoleListView(StoreScopedPermissionMixin, ListView):
    """List all roles visible to the current user."""

    template_name = "role_permission/roles/role_list.html"
    context_object_name = "roles"
    paginate_by = 20
    required_permission = PERM_ROLES_VIEW

    def get_queryset(self):
        qs = (
            Role.objects
            .select_related("store", "inherits_from")
            .annotate(permission_count=Count("role_permissions"))
        )

        if self.request.user.is_superuser:
            store_filter = self.request.GET.get("store")
            if store_filter:
                qs = qs.filter(store_id=store_filter)
        else:
            store = self.get_current_store()
            qs = qs.filter(Q(store__isnull=True) | Q(store=store))

        search = self.request.GET.get("q", "").strip()
        if search:
            qs = qs.filter(
                Q(name__icontains=search) | Q(slug__icontains=search)
                | Q(description__icontains=search)
            )

        level = self.request.GET.get("level")
        if level and level.isdigit():
            qs = qs.filter(level=int(level))

        return qs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        current_store = self.get_current_store()
        ctx["current_store"] = current_store
        ctx["is_superuser"] = self.request.user.is_superuser

        if self.request.user.is_superuser:
            ctx["admin_stores"] = get_user_stores_for_admin(self.request.user)
        else:
            ctx["admin_stores"] = (
                Store.objects.filter(id=current_store.id) if current_store else Store.objects.none()
            )

        ctx["level_choices"] = [
            (Role.LEVEL_OWNER, "Owner"),
            (Role.LEVEL_ADMIN, "Admin"),
            (Role.LEVEL_MANAGER, "Manager"),
            (Role.LEVEL_STAFF, "Staff"),
            (Role.LEVEL_VIEWER, "Viewer"),
            (Role.LEVEL_CUSTOM, "Custom"),
        ]
        ctx["can_manage"] = (
            self.request.user.is_superuser
            or (current_store and user_has_permission(
                self.request.user, current_store, PERM_ROLES_MANAGE,
            ))
        )
        ctx["search_query"] = self.request.GET.get("q", "")
        ctx["level_filter"] = self.request.GET.get("level", "")
        return ctx


class RoleDetailView(StoreScopedPermissionMixin, DetailView):
    """Show a role and its current permission set."""

    template_name = "role_permission/roles/role_detail.html"
    context_object_name = "role"
    model = Role
    required_permission = PERM_ROLES_VIEW
    slug_url_kwarg = "role_id"

    def get_object(self, queryset=None):
        role = get_object_or_404(Role, id=self.kwargs["role_id"])
        if not self.request.user.is_superuser:
            store = self.get_current_store()
            if role.store_id and role.store_id != store.id:
                from django.core.exceptions import PermissionDenied
                raise PermissionDenied
        return role

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        role = self.object
        current_store = self.get_current_store()

        role_perm_ids = {
            str(p) for p in
            role.role_permissions.values_list("permission_id", flat=True)
        }

        resources = (
            Resource.objects
            .filter(is_active=True)
            .prefetch_related(
                Prefetch("permissions", queryset=Permission.objects.order_by("action"))
            )
            .order_by("category", "code")
        )

        grouped = []
        for resource in resources:
            perms = list(resource.permissions.all())
            perm_data = [
                {
                    "id": str(p.id),
                    "code": p.code,
                    "action": p.action,
                    "name": p.name,
                    "granted": str(p.id) in role_perm_ids,
                }
                for p in perms
            ]
            grouped.append({
                "resource": resource,
                "permissions": perm_data,
                "granted_count": sum(1 for p in perm_data if p["granted"]),
                "total_count": len(perm_data),
            })

        ctx["grouped_permissions"] = grouped
        ctx["granted_count"] = len(role_perm_ids)
        ctx["total_count"] = Permission.objects.count()
        ctx["current_store"] = current_store
        ctx["is_superuser"] = self.request.user.is_superuser

        can_manage = self.request.user.is_superuser or (
            current_store and user_has_permission(
                self.request.user, current_store, PERM_ROLES_MANAGE,
            )
        )
        ctx["can_manage"] = can_manage and (not role.is_system or self.request.user.is_superuser)
        ctx["can_delete"] = ctx["can_manage"] and not role.is_system
        return ctx


class RoleCreateView(StoreScopedPermissionMixin, CreateView):
    """Create a new role (custom or system)."""

    template_name = "role_permission/roles/role_form.html"
    form_class = RoleForm
    required_permission = PERM_ROLES_MANAGE

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["actor"] = self.request.user
        kwargs["store"] = self.get_current_store()
        return kwargs

    def get_initial(self):
        return super().get_initial() | {"is_active": True}

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["grouped_permissions"] = build_permission_groups(self.object, ctx.get("form"))
        ctx["current_store"] = self.get_current_store()
        ctx["is_superuser"] = self.request.user.is_superuser
        return ctx

    def form_valid(self, form):
        store = self.get_current_store()
        is_system = (
            form.cleaned_data.get("is_system", False) and self.request.user.is_superuser
        )
        try:
            role = services.create_role(
                actor=self.request.user,
                store=None if is_system else store,
                name=form.cleaned_data["name"],
                description=form.cleaned_data.get("description", ""),
                is_system=is_system,
                level=form.cleaned_data.get("level", Role.LEVEL_CUSTOM),
                inherits_from=form.cleaned_data.get("inherits_from"),
                request=self.request,
            )
            services.set_role_permissions(
                actor=self.request.user,
                role=role,
                permission_ids=[p.id for p in form.cleaned_data.get("permissions", [])],
                modifier="grant",
                request=self.request,
            )
        except (PermissionError, ValueError) as exc:
            messages.error(self.request, str(exc))
            return self.form_invalid(form)

        messages.success(self.request, f"Role '{role.name}' created successfully.")
        return redirect("role_permission:role_detail", role_id=str(role.id))


class RoleUpdateView(StoreScopedPermissionMixin, UpdateView):
    """Edit an existing role."""

    template_name = "role_permission/roles/role_form.html"
    form_class = RoleForm
    model = Role
    required_permission = PERM_ROLES_MANAGE
    slug_url_kwarg = "role_id"

    def get_object(self, queryset=None):
        return get_object_or_404(Role, id=self.kwargs["role_id"])

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["actor"] = self.request.user
        kwargs["store"] = self.get_current_store()
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["grouped_permissions"] = build_permission_groups(self.object, ctx.get("form"))
        ctx["current_store"] = self.get_current_store()
        ctx["is_superuser"] = self.request.user.is_superuser
        return ctx

    def form_valid(self, form):
        role = self.object
        try:
            services.update_role(
                actor=self.request.user,
                role=role,
                name=form.cleaned_data.get("name"),
                description=form.cleaned_data.get("description"),
                level=form.cleaned_data.get("level"),
                is_active=form.cleaned_data.get("is_active"),
                request=self.request,
            )
            services.set_role_permissions(
                actor=self.request.user,
                role=role,
                permission_ids=[p.id for p in form.cleaned_data.get("permissions", [])],
                modifier="grant",
                request=self.request,
            )
        except (PermissionError, ValueError) as exc:
            messages.error(self.request, str(exc))
            return self.form_invalid(form)

        messages.success(self.request, f"Role '{role.name}' updated.")
        return redirect("role_permission:role_detail", role_id=str(role.id))


class RoleDeleteView(StoreScopedPermissionMixin, View):
    """POST-only delete endpoint."""

    required_permission = PERM_ROLES_MANAGE

    def post(self, request: HttpRequest, role_id: str) -> HttpResponse:
        role = get_object_or_404(Role, id=role_id)
        try:
            services.delete_role(actor=request.user, role=role, request=request)
        except PermissionError as exc:
            messages.error(request, str(exc))
            return redirect("role_permission:role_detail", role_id=str(role.id))

        messages.success(request, f"Role '{role.name}' has been removed.")
        return redirect("role_permission:role_list")


class RoleCloneView(StoreScopedPermissionMixin, View):
    """Clone an existing role with a new name."""

    required_permission = PERM_ROLES_MANAGE

    def post(self, request: HttpRequest, role_id: str) -> HttpResponse:
        role = get_object_or_404(Role, id=role_id)
        form = RoleCloneForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Please provide a valid name for the cloned role.")
            return redirect("role_permission:role_detail", role_id=str(role.id))

        try:
            new_role = services.clone_role(
                actor=request.user,
                role=role,
                new_name=form.cleaned_data["new_name"],
                request=request,
            )
        except (PermissionError, ValueError) as exc:
            messages.error(request, str(exc))
            return redirect("role_permission:role_detail", role_id=str(role.id))

        messages.success(request, f"Cloned '{role.name}' as '{new_role.name}'.")
        return redirect("role_permission:role_detail", role_id=str(new_role.id))


# ---------------------------------------------------------------------------
# AJAX: toggle a single permission on a role
# ---------------------------------------------------------------------------
class RolePermissionToggleView(StoreScopedPermissionMixin, View):
    """AJAX endpoint: POST to toggle a single permission on a role."""

    required_permission = PERM_ROLES_MANAGE

    def post(self, request: HttpRequest, role_id: str) -> JsonResponse:
        role = get_object_or_404(Role, id=role_id)
        try:
            payload = json.loads(request.body or "{}")
            permission_id = payload.get("permission_id")
            if not permission_id:
                return JsonResponse({"error": "permission_id is required"}, status=400)
            granted = services.toggle_role_permission(
                actor=request.user,
                role=role,
                permission_id=permission_id,
                request=request,
            )
        except PermissionError as exc:
            return JsonResponse({"error": str(exc)}, status=403)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON body"}, status=400)

        return JsonResponse({
            "role_id": str(role.id),
            "permission_id": str(permission_id),
            "granted": granted,
        })


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------
class MemberListView(StoreScopedPermissionMixin, ListView):
    """List members of the current store."""

    template_name = "role_permission/members/member_list.html"
    context_object_name = "members"
    paginate_by = 25
    required_permission = PERM_MEMBERS_VIEW

    def get_queryset(self):
        store = self.get_current_store()
        qs = (
            StoreMembership.objects
            .filter(store=store)
            .select_related("user", "role", "invited_by")
        )
        search = self.request.GET.get("q", "").strip()
        if search:
            qs = qs.filter(
                Q(user__email__icontains=search)
                | Q(user__first_name__icontains=search)
                | Q(user__last_name__icontains=search)
                | Q(role__name__icontains=search)
            )
        role_filter = self.request.GET.get("role")
        if role_filter:
            qs = qs.filter(role_id=role_filter)
        status = self.request.GET.get("status", "active")
        if status == "active":
            qs = qs.filter(is_active=True)
        elif status == "inactive":
            qs = qs.filter(is_active=False)
        return qs.order_by("-is_active", "user__email")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        current_store = self.get_current_store()
        ctx["current_store"] = current_store
        ctx["can_manage"] = (
            self.request.user.is_superuser
            or (current_store and user_has_permission(
                self.request.user, current_store, PERM_MEMBERS_MANAGE,
            ))
        )
        ctx["available_roles"] = (
            Role.objects.filter(is_active=True)
            .filter(Q(store__isnull=True) | Q(store=current_store))
            .order_by("-level", "name")
        )
        ctx["search_query"] = self.request.GET.get("q", "")
        ctx["role_filter"] = self.request.GET.get("role", "")
        ctx["status_filter"] = self.request.GET.get("status", "active")
        return ctx


class MemberAddView(StoreScopedPermissionMixin, View):
    """Add a new member to the current store."""

    required_permission = PERM_MEMBERS_MANAGE

    def get(self, request: HttpRequest) -> HttpResponse:
        store = self.get_current_store()
        form = MembershipForm(store=store)
        return render(request, "role_permission/members/member_add.html", {
            "form": form,
            "current_store": store,
        })

    def post(self, request: HttpRequest) -> HttpResponse:
        store = self.get_current_store()
        form = MembershipForm(request.POST, store=store)
        if not form.is_valid():
            return render(request, "role_permission/members/member_add.html", {
                "form": form,
                "current_store": store,
            }, status=400)

        try:
            services.add_member(
                actor=request.user,
                store=store,
                user=form.cleaned_data["_user"],
                role=form.cleaned_data["role"],
                expires_at=form.cleaned_data.get("expires_at"),
                request=request,
            )
        except PermissionError as exc:
            messages.error(request, str(exc))
            return redirect("role_permission:member_add")

        messages.success(
            request,
            f"Added {form.cleaned_data['_user'].email} as {form.cleaned_data['role'].name}.",
        )
        return redirect("role_permission:member_list")


class MemberChangeRoleView(StoreScopedPermissionMixin, View):
    """Change a member's role (AJAX)."""

    required_permission = PERM_MEMBERS_MANAGE

    def post(self, request: HttpRequest, membership_id: str) -> JsonResponse:
        membership = get_object_or_404(
            StoreMembership,
            id=membership_id,
            store=self.get_current_store(),
        )
        try:
            payload = json.loads(request.body or "{}")
            new_role_id = payload.get("role_id")
            new_role = get_object_or_404(Role, id=new_role_id, is_active=True)
            services.change_member_role(
                actor=request.user,
                membership=membership,
                new_role=new_role,
                request=request,
            )
        except PermissionError as exc:
            return JsonResponse({"error": str(exc)}, status=403)
        except (ValueError, json.JSONDecodeError) as exc:
            return JsonResponse({"error": str(exc)}, status=400)

        return JsonResponse({
            "membership_id": str(membership.id),
            "new_role_id": str(new_role.id),
            "new_role_name": new_role.name,
        })


class MemberDeactivateView(StoreScopedPermissionMixin, View):
    """Deactivate a membership (AJAX)."""

    required_permission = PERM_MEMBERS_MANAGE

    def post(self, request: HttpRequest, membership_id: str) -> JsonResponse:
        membership = get_object_or_404(
            StoreMembership,
            id=membership_id,
            store=self.get_current_store(),
        )
        try:
            services.deactivate_member(
                actor=request.user, membership=membership, request=request,
            )
        except PermissionError as exc:
            return JsonResponse({"error": str(exc)}, status=403)
        return JsonResponse({"membership_id": str(membership.id), "is_active": False})


class MemberReactivateView(StoreScopedPermissionMixin, View):
    """Reactivate a previously deactivated membership (AJAX)."""

    required_permission = PERM_MEMBERS_MANAGE

    def post(self, request: HttpRequest, membership_id: str) -> JsonResponse:
        membership = get_object_or_404(
            StoreMembership,
            id=membership_id,
            store=self.get_current_store(),
        )
        try:
            services.reactivate_member(
                actor=request.user, membership=membership, request=request,
            )
        except PermissionError as exc:
            return JsonResponse({"error": str(exc)}, status=403)
        return JsonResponse({"membership_id": str(membership.id), "is_active": True})


# ---------------------------------------------------------------------------
# User permission overrides
# ---------------------------------------------------------------------------
class OverrideListView(StoreScopedPermissionMixin, ListView):
    """List per-user permission overrides (grants and denies)."""

    template_name = "role_permission/overrides/override_list.html"
    context_object_name = "overrides"
    paginate_by = 25
    required_permission = PERM_PERMISSIONS_OVERRIDE

    def get_queryset(self):
        qs = (
            UserPermissionOverride.objects
            .select_related("user", "permission", "permission__resource", "store", "granted_by")
        )

        if self.request.user.is_superuser:
            store_filter = self.request.GET.get("store")
            if store_filter:
                qs = qs.filter(store_id=store_filter)
        else:
            store = self.get_current_store()
            qs = qs.filter(Q(store__isnull=True) | Q(store=store))

        search = self.request.GET.get("q", "").strip()
        if search:
            qs = qs.filter(
                Q(user__email__icontains=search)
                | Q(user__first_name__icontains=search)
                | Q(user__last_name__icontains=search)
                | Q(permission__code__icontains=search)
                | Q(reason__icontains=search)
            )

        kind = self.request.GET.get("kind")
        if kind in ("grant", "deny"):
            qs = qs.filter(is_granted=(kind == "grant"))

        active = self.request.GET.get("active")
        if active == "yes":
            qs = qs.filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
        elif active == "no":
            qs = qs.filter(expires_at__lte=timezone.now())

        return qs.order_by("-created_at")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["current_store"] = self.get_current_store()
        ctx["is_superuser"] = self.request.user.is_superuser

        if self.request.user.is_superuser:
            ctx["admin_stores"] = get_user_stores_for_admin(self.request.user)
        else:
            store = self.get_current_store()
            ctx["admin_stores"] = (
                Store.objects.filter(id=store.id) if store else Store.objects.none()
            )

        ctx["can_manage"] = (
            self.request.user.is_superuser
            or (ctx["current_store"] and user_has_permission(
                self.request.user, ctx["current_store"], PERM_PERMISSIONS_OVERRIDE,
            ))
        )
        ctx["search_query"] = self.request.GET.get("q", "")
        ctx["kind_filter"] = self.request.GET.get("kind", "")
        ctx["active_filter"] = self.request.GET.get("active", "")
        ctx["store_filter"] = self.request.GET.get("store", "")
        return ctx


class OverrideCreateView(StoreScopedPermissionMixin, CreateView):
    """Create a new per-user override."""

    template_name = "role_permission/overrides/override_form.html"
    form_class = UserOverrideForm
    required_permission = PERM_PERMISSIONS_OVERRIDE

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["actor"] = self.request.user
        kwargs["store"] = self.get_current_store()
        return kwargs

    def form_valid(self, form):
        try:
            override = services.set_user_override(
                actor=self.request.user,
                target_user=form.cleaned_data["user"],
                store=self.get_current_store(),
                permission=form.cleaned_data["permission"],
                is_granted=form.cleaned_data["is_granted"],
                reason=form.cleaned_data.get("reason", ""),
                expires_at=form.cleaned_data.get("expires_at"),
                request=self.request,
            )
        except PermissionError as exc:
            messages.error(self.request, str(exc))
            return self.form_invalid(form)

        messages.success(
            self.request,
            f"Override for {form.cleaned_data['user'].email} saved.",
        )
        return redirect("role_permission:override_list")


class OverrideUpdateView(StoreScopedPermissionMixin, UpdateView):
    """Edit an existing override."""

    template_name = "role_permission/overrides/override_form.html"
    form_class = UserOverrideForm
    model = UserPermissionOverride
    required_permission = PERM_PERMISSIONS_OVERRIDE
    pk_url_kwarg = "override_id"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["actor"] = self.request.user
        kwargs["store"] = self.get_current_store()
        return kwargs

    def form_valid(self, form):
        override = self.object
        try:
            services.set_user_override(
                actor=self.request.user,
                target_user=form.cleaned_data["user"],
                store=override.store,
                permission=form.cleaned_data["permission"],
                is_granted=form.cleaned_data["is_granted"],
                reason=form.cleaned_data.get("reason", ""),
                expires_at=form.cleaned_data.get("expires_at"),
                request=self.request,
            )
        except PermissionError as exc:
            messages.error(self.request, str(exc))
            return self.form_invalid(form)

        messages.success(self.request, "Override updated.")
        return redirect("role_permission:override_list")


class OverrideDeleteView(StoreScopedPermissionMixin, View):
    """Remove a per-user override (POST-only)."""

    required_permission = PERM_PERMISSIONS_OVERRIDE

    def post(self, request: HttpRequest, override_id: str) -> HttpResponse:
        override = get_object_or_404(UserPermissionOverride, id=override_id)
        try:
            services.clear_user_override(
                actor=request.user, override=override, request=request,
            )
        except PermissionError as exc:
            messages.error(request, str(exc))
            return redirect("role_permission:override_list")

        messages.success(request, "Override removed.")
        return redirect("role_permission:override_list")


# ---------------------------------------------------------------------------
# Permission catalog (read-only)
# ---------------------------------------------------------------------------
class PermissionCatalogView(StoreScopedPermissionMixin, ListView):
    """Display the full permission catalog, grouped by resource."""

    template_name = "role_permission/permissions/permission_catalog.html"
    context_object_name = "resources"
    required_permission = PERM_PERMISSIONS_VIEW
    paginate_by = 50

    def get_queryset(self):
        return (
            Resource.objects
            .filter(is_active=True)
            .prefetch_related(
                Prefetch("permissions", queryset=Permission.objects.order_by("action"))
            )
            .order_by("category", "code")
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["current_store"] = self.get_current_store()
        return ctx


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------
class AuditLogListView(StoreScopedPermissionMixin, ListView):
    """List recent audit-log entries, filterable."""

    template_name = "role_permission/audit/audit_log.html"
    context_object_name = "events"
    paginate_by = 50
    required_permission = PERM_AUDIT_VIEW

    def get_queryset(self):
        store = self.get_current_store()
        qs = AuditLog.objects.select_related("actor", "store")

        if not self.request.user.is_superuser:
            qs = qs.filter(store=store)

        action = self.request.GET.get("action")
        if action:
            qs = qs.filter(action=action)
        target_type = self.request.GET.get("target_type")
        if target_type:
            qs = qs.filter(target_type=target_type)
        actor_id = self.request.GET.get("actor")
        if actor_id:
            qs = qs.filter(actor_id=actor_id)

        return qs.order_by("-created_at")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["current_store"] = self.get_current_store()
        ctx["is_superuser"] = self.request.user.is_superuser
        ctx["action_filter"] = self.request.GET.get("action", "")
        ctx["target_type_filter"] = self.request.GET.get("target_type", "")
        return ctx


class AuditLogExportView(SuperuserOnlyMixin, View):
    """CSV export of the audit log (superuser only)."""

    def get(self, request: HttpRequest) -> HttpResponse:
        import csv

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="audit_log.csv"'
        writer = csv.writer(response)
        writer.writerow([
            "created_at", "action", "target_type", "target_id",
            "actor_email", "store_id", "ip", "request_id",
        ])
        qs = AuditLog.objects.select_related("actor", "store")
        action = request.GET.get("action")
        if action:
            qs = qs.filter(action=action)
        for row in qs.order_by("-created_at")[:5000]:
            writer.writerow([
                row.created_at.isoformat(),
                row.action,
                row.target_type,
                row.target_id,
                row.actor.email if row.actor else "",
                str(row.store_id) if row.store_id else "",
                row.ip_address or "",
                row.request_id or "",
            ])
        return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def build_permission_groups(role, form):
    """
    Return the permission registry grouped by Resource, ready for rendering.

    Each entry is a dict suitable for the role form's grouped layout:
        {
            "resource": Resource instance,
            "permissions": [ {id, code, action, name, granted, choice} ],
            "granted_count": int,
            "total_count": int,
        }
    Where ``choice`` is the BoundField for the form's `permissions` M2M
    field that matches the permission id, so the template can render
    `<input type="checkbox">` without iterating the whole flat M2M.
    """
    # Index BoundField choices by permission id (string)
    field = form["permissions"] if form else None
    choices_by_id: dict[str, Any] = {}
    if field is not None:
        # `field` is a BoundField; its subwidgets are the checkboxes
        for choice in field:
            # subwidget name ends with the value; the value is at the end
            value = choice.data.get("value") if isinstance(choice.data, dict) else None
            if value is not None:
                choices_by_id[str(value)] = choice

    selected_ids: set[str] = set()
    if role is not None and getattr(role, "pk", None):
        selected_ids = {
            str(pid)
            for pid in role.role_permissions.values_list("permission_id", flat=True)
        }

    resources = (
        Resource.objects
        .filter(is_active=True)
        .prefetch_related(
            Prefetch("permissions", queryset=Permission.objects.order_by("action"))
        )
        .order_by("category", "code")
    )

    groups = []
    for resource in resources:
        perms = list(resource.permissions.all())
        perm_data = []
        granted = 0
        for p in perms:
            pid = str(p.id)
            is_selected = pid in selected_ids
            if is_selected:
                granted += 1
            perm_data.append({
                "id": pid,
                "code": p.code,
                "action": p.action,
                "name": p.name,
                "granted": is_selected,
                "choice": choices_by_id.get(pid),
            })
        groups.append({
            "resource": resource,
            "permissions": perm_data,
            "granted_count": granted,
            "total_count": len(perm_data),
        })
    return groups
