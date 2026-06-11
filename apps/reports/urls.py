"""
URL configuration for reports app (placeholder).
"""

from django.urls import path

from apps.common.views_placeholder import placeholder_view

app_name = "reports"

urlpatterns = [
    path("sales/", placeholder_view, {"app_name": "Sales Reports"}, name="sales"),
    path("customers/", placeholder_view, {"app_name": "Customer Reports"}, name="customers"),
    path("products/", placeholder_view, {"app_name": "Product Reports"}, name="products"),
]