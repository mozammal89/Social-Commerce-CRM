"""
URL configuration for help app (placeholder).
"""

from django.urls import path

from apps.common.views_placeholder import placeholder_view

app_name = "help"

urlpatterns = [
    path("documentation/", placeholder_view, {"app_name": "Documentation"}, name="documentation"),
    path("support/", placeholder_view, {"app_name": "Support"}, name="support"),
]