"""
Django AppConfig for the role/permission management UI.

This is registered as a sub-app of ``apps.permissions`` so the core
RBAC models and the UI share the same app registry but stay logically
separated.
"""

from django.apps import AppConfig


class PermissionsUiConfig(AppConfig):
    """Configuration for the role/permission management UI."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.permissions.ui"
    label = "permissions_ui"
    verbose_name = "Role & Permission Management UI"
