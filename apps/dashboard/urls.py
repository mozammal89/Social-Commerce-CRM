"""
URL configuration for dashboard app.
"""

from django.urls import path

from apps.dashboard.views import dashboard_home, switch_store
from apps.common.views_placeholder import placeholder_view

app_name = "dashboard"

urlpatterns = [
    path("", dashboard_home, name="home"),
    path("", dashboard_home, name="index"),
    path("notifications/", placeholder_view, {"app_name": "Notifications"}, name="notifications"),
    path("switch-store/<uuid:store_id>/", switch_store, name="switch_store"),
]