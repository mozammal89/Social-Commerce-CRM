"""
URL configuration for products app (placeholder).
"""

from django.urls import path

from apps.common.views_placeholder import placeholder_view

app_name = "products"

urlpatterns = [
    path("", placeholder_view, {"app_name": "Products"}, name="list"),
    path("create/", placeholder_view, {"app_name": "Products"}, name="create"),
    path("inventory/", placeholder_view, {"app_name": "Products"}, name="inventory"),
]