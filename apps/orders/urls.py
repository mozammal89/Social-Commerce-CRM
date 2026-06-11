"""
URL configuration for orders app (placeholder).
"""

from django.urls import path

from apps.common.views_placeholder import placeholder_view

app_name = "orders"

urlpatterns = [
    path("", placeholder_view, {"app_name": "Orders"}, name="list"),
    path("create/", placeholder_view, {"app_name": "Orders"}, name="create"),
    path("pending/", placeholder_view, {"app_name": "Orders"}, name="pending"),
    path("processing/", placeholder_view, {"app_name": "Orders"}, name="processing"),
    path("completed/", placeholder_view, {"app_name": "Orders"}, name="completed"),
]