"""
Demo Application to demonstrate RBAC system workflow

This app shows the complete process of adding new views with permissions
and syncing the RBAC system.
"""

from django.apps import AppConfig


class DemoConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.demo"
    verbose_name = "RBAC Demo"
