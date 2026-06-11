"""
URL configuration for customers app (placeholder).
"""

from django.urls import path

from apps.common.views_placeholder import placeholder_view

app_name = "customers"

urlpatterns = [
    path("", placeholder_view, {"app_name": "Customers"}, name="list"),
    path("create/", placeholder_view, {"app_name": "Customers"}, name="create"),
]