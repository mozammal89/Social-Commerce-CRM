"""
URL configuration for marketing app (placeholder).
"""

from django.urls import path

from apps.common.views_placeholder import placeholder_view

app_name = "marketing"

urlpatterns = [
    path("campaigns/", placeholder_view, {"app_name": "Marketing Campaigns"}, name="campaigns"),
    path("promotions/", placeholder_view, {"app_name": "Marketing Promotions"}, name="promotions"),
    path("analytics/", placeholder_view, {"app_name": "Marketing Analytics"}, name="analytics"),
]