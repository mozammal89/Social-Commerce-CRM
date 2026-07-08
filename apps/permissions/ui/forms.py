"""
Forms for the role/permission management UI.
"""

from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.text import slugify

from apps.permissions.constants import MODIFIER_GRANT
from apps.permissions.models import (
    Permission,
    Role,
    StoreMembership,
    UserPermissionOverride,
)
from apps.stores.models import Store


def str_to_bool(value):
    """Convert string values to boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "t")
    return bool(value)


class RoleForm(forms.ModelForm):
    """Create/edit a role."""

    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.none(),  # populated in __init__
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Select which permissions this role grants.",
    )

    class Meta:
        model = Role
        fields = ("name", "description", "level", "is_active", "inherits_from")
        widgets = {
            "name": forms.TextInput(attrs={"required": "required", "class": "form-control"}),
            "description": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "level": forms.NumberInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "inherits_from": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, actor=None, store=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["permissions"].queryset = Permission.objects.select_related(
            "resource"
        ).order_by("resource__category", "resource__code", "action")

        # Only superusers may toggle is_system
        if not (actor and actor.is_superuser):
            self.fields.pop("is_system", None)
            if self.instance and self.instance.is_system:
                for fname in ("name", "level", "is_active", "inherits_from"):
                    if fname in self.fields:
                        self.fields[fname].disabled = True

        # Pre-select current permissions when editing
        if self.instance and self.instance.pk:
            current = self.instance.role_permissions.values_list("permission_id", flat=True)
            self.fields["permissions"].initial = list(current)

    def clean(self):
        cleaned = super().clean()
        name = cleaned.get("name")
        if name:
            slug = slugify(name)
            qs = Role.objects.filter(slug=slug)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError({"name": "A role with a similar name already exists."})
        return cleaned


class RoleCloneForm(forms.Form):
    """Form for cloning a role."""

    new_name = forms.CharField(
        max_length=128,
        label="New role name",
        help_text="The cloned role will be created with this name.",
    )


class MembershipForm(forms.Form):
    """Form to invite/add a member to a store."""

    email = forms.EmailField(
        label="User email",
        help_text="The user must already have an account.",
        required=True,
        widget=forms.EmailInput(attrs={"required": "required", "class": "form-control"}),
    )
    role = forms.ModelChoiceField(
        queryset=Role.objects.none(),
        label="Role",
        help_text="The role to assign in this store.",
        required=True,
        widget=forms.Select(attrs={"required": "required", "class": "form-select"}),
    )
    expires_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
        help_text="Optional: membership auto-expires at this time.",
    )

    def __init__(self, *args, store=None, **kwargs):
        super().__init__(*args, **kwargs)
        if store is not None:
            self.fields["role"].queryset = (
                Role.objects.filter(is_active=True)
                .filter(Q(store__isnull=True) | Q(store=store))
                .order_by("-level", "name")
            )
        self._store = store

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get("email")
        role = cleaned.get("role")
        store = self._store
        if email and role and store is not None:
            from django.contrib.auth import get_user_model

            User = get_user_model()
            try:
                user = User.objects.get(email__iexact=email)
            except User.DoesNotExist:
                raise forms.ValidationError({"email": "No user found with that email address."})
            cleaned["_user"] = user

            existing = StoreMembership.objects.filter(
                user=user,
                store=store,
                role=role,
                is_active=True,
            )
            if existing.exists():
                raise forms.ValidationError(
                    {"email": "This user already has an active membership with that role."}
                )
        return cleaned


class UserOverrideForm(forms.ModelForm):
    """Form for setting a per-user permission override.
    One override = one specific permission with grant/deny flag.
    """

    user = forms.ModelChoiceField(
        queryset=get_user_model().objects.all().order_by("email"),
        label="User",
        help_text="The user receiving this override.",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    is_granted = forms.ChoiceField(
        choices=[
            (True, "GRANT"),
            (False, "DENY"),
        ],
        initial=True,
        label="Override Type",
        help_text="Grant gives permission, Deny blocks it.",
        widget=forms.RadioSelect(attrs={"class": "form-check-input"}),
    )

    class Meta:
        model = UserPermissionOverride
        fields = ("user", "permission", "is_granted", "reason", "expires_at")
        widgets = {
            "permission": forms.Select(attrs={"class": "form-select"}),
            "reason": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "expires_at": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "form-control"}
            ),
        }

    def clean_is_granted(self):
        """Convert string 'True'/'False' to boolean."""
        value = self.cleaned_data.get("is_granted")
        if value in (True, "True", "true", "1", 1):
            return True
        elif value in (False, "False", "false", "0", 0):
            return False
        else:
            # Default to True if value is unknown
            return True

    def __init__(self, *args, actor=None, store=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["permission"].queryset = Permission.objects.select_related("resource").order_by(
            "resource__category", "resource__code", "action"
        )

        # Filter user field and permission field for non-superusers
        if actor and not actor.is_superuser and store:
            # Filter user field: only show users who are members of this store
            store_member_ids = StoreMembership.objects.filter(
                store=store,
                is_active=True
            ).values_list("user_id", flat=True)
            self.fields["user"].queryset = get_user_model().objects.filter(
                id__in=store_member_ids
            ).order_by("email")

            # Filter permission field: only show permissions the actor has
            # Get actor's membership and role for this store
            actor_membership = StoreMembership.objects.filter(
                user=actor,
                store=store,
                is_active=True
            ).first()

            if actor_membership and actor_membership.role:
                # Get permissions from the actor's role
                role_perm_ids = actor_membership.role.role_permissions.values_list(
                    "permission_id", flat=True
                )
                self.fields["permission"].queryset = Permission.objects.filter(
                    id__in=role_perm_ids
                ).select_related("resource").order_by(
                    "resource__category", "resource__code", "action"
                )

        # Only set initial user + lock the field if the override already
        # has a user assigned. A fresh instance has no `user_id` yet.
        if self.instance and self.instance.pk and getattr(self.instance, "user_id", None):
            self.fields["user"].initial = self.instance.user
            self.fields["user"].disabled = True
        if not (actor and actor.is_superuser):
            self.fields["store"] = forms.ModelChoiceField(
                queryset=Store.objects.filter(id=store.id) if store else Store.objects.none(),
                disabled=True,
                required=False,
            )
