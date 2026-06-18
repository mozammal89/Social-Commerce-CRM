"""
Forms for the role/permission management UI.
"""

from __future__ import annotations

from django import forms
from django.db.models import Q

from apps.permissions.constants import MODIFIER_CHOICES, MODIFIER_GRANT
from apps.permissions.models import (
    Permission,
    Role,
    StoreMembership,
    UserPermissionOverride,
)
from apps.stores.models import Store


class RoleForm(forms.ModelForm):
    """Create/edit a role."""

    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.none(),  # populated in __init__
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Select which permissions this role grants.",
    )

    modifier = forms.ChoiceField(
        choices=MODIFIER_CHOICES,
        initial=MODIFIER_GRANT,
        widget=forms.RadioSelect,
        help_text="Grant allows the action; Deny explicitly forbids it.",
    )

    class Meta:
        model = Role
        fields = ("name", "description", "level", "is_active", "inherits_from")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, actor=None, store=None, **kwargs):
        super().__init__(*args)
        self.fields["permissions"].queryset = (
            Permission.objects
            .select_related("resource")
            .order_by("resource__category", "resource__code", "action")
        )

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
            from django.utils.text import slugify
            slug = slugify(name)
            qs = Role.objects.filter(slug=slug)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    {"name": "A role with a similar name already exists."}
                )
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
    )
    role = forms.ModelChoiceField(
        queryset=Role.objects.none(),
        label="Role",
        help_text="The role to assign in this store.",
    )
    expires_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        help_text="Optional: membership auto-expires at this time.",
    )

    def __init__(self, *args, store=None, **kwargs):
        super().__init__(*args)
        if store is not None:
            self.fields["role"].queryset = (
                Role.objects
                .filter(is_active=True)
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
                raise forms.ValidationError(
                    {"email": "No user found with that email address."}
                )
            cleaned["_user"] = user

            existing = StoreMembership.objects.filter(
                user=user, store=store, role=role, is_active=True,
            )
            if existing.exists():
                raise forms.ValidationError(
                    {"email": "This user already has an active membership with that role."}
                )
        return cleaned


class UserOverrideForm(forms.ModelForm):
    """Form for setting a per-user permission override."""

    class Meta:
        model = UserPermissionOverride
        fields = ("permission", "is_granted", "reason", "expires_at")
        widgets = {
            "expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, actor=None, store=None, **kwargs):
        super().__init__(*args)
        self.fields["permission"].queryset = (
            Permission.objects.select_related("resource")
            .order_by("resource__code", "action")
        )
        if not (actor and actor.is_superuser):
            self.fields["store"] = forms.ModelChoiceField(
                queryset=Store.objects.filter(id=store.id) if store else Store.objects.none(),
                disabled=True,
                required=False,
            )
