"""
URL configuration for core app.

This file contains API health check endpoints and landing page.
Served at /api/v1/health/
"""

from django.urls import path

from apps.core.views import health_check, DetailedHealthCheckView, landing_home

app_name = "core"

urlpatterns = [
    path("", health_check, name="health_check"),
    path("detailed/", DetailedHealthCheckView.as_view(), name="detailed_health_check"),
    path("landing/", landing_home, name="landing_home"),
]
