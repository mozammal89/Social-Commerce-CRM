"""
URL configuration for settings app (placeholder).
"""

from django.urls import path

from apps.common.views_placeholder import placeholder_view

app_name = "settings"

urlpatterns = [
    path("store/", placeholder_view, {"app_name": "Store Settings"}, name="store"),
    path("team/", placeholder_view, {"app_name": "Team Settings"}, name="team"),
    path("integrations/", placeholder_view, {"app_name": "Integrations"}, name="integrations"),
    path("billing/", placeholder_view, {"app_name": "Billing"}, name="billing"),
]