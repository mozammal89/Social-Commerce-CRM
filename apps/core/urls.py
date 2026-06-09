"""
URL configuration for core app.
"""

from django.urls import path
from apps.core.views import health_check, DetailedHealthCheckView

app_name = "core"

urlpatterns = [
    path("", health_check, name="health"),
    path("detailed/", DetailedHealthCheckView.as_view(), name="health_detailed"),
]
