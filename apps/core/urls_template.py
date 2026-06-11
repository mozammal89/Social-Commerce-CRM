"""
Template-based URL configuration for core app.
"""

from django.urls import path

from apps.core.views_template import home

app_name = "core"

urlpatterns = [
    path("", home, name="home"),
]