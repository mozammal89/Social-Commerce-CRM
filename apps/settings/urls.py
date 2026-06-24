"""
URL configuration for settings app.

The "team" route is now backed by the full role/permission UI at
``/dashboard/roles/members/``. Older clients that bookmarked
``/settings/team/`` are redirected there.
"""

from django.urls import path
from django.urls.resolvers import URLPattern
from django.views.generic import RedirectView

from apps.common.views_placeholder import placeholder_view

app_name = "settings"

urlpatterns: list[URLPattern] = [
    path("store/", placeholder_view, {"app_name": "Store Settings"}, name="store"),
    path(
        "team/",
        RedirectView.as_view(
            url="/dashboard/roles/members/", permanent=False,
        ),
        name="team",
    ),
    path("integrations/", placeholder_view, {"app_name": "Integrations"}, name="integrations"),
    path("billing/", placeholder_view, {"app_name": "Billing"}, name="billing"),
]