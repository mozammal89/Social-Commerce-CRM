"""
URL configuration for settings app.
"""

from django.urls import path, include
from apps.settings import views

app_name = "settings"

urlpatterns = [
    path("store/<uuid:store_id>/", views.store_settings, name="store"),
    path("team/<uuid:store_id>/", views.team_management, name="team",),
    path("team/<uuid:store_id>/invite/", views.invite_member, name="invite_member",),
    path(
        "team/<uuid:store_id>/change-role/<uuid:membership_id>/",
        views.change_member_role,
        name="change_member_role",
    ),
    path(
        "team/<uuid:store_id>/deactivate/<uuid:membership_id>/",
        views.deactivate_member,
        name="deactivate_member",
    ),
    path(
        "team/<uuid:store_id>/activate/<uuid:membership_id>/",
        views.activate_member,
        name="activate_member",
    ),
    path(
        "team/<uuid:store_id>/remove/<uuid:membership_id>/",
        views.remove_member,
        name="remove_member",
    ),
    path("integrations/<uuid:store_id>/", views.integrations, name="integrations"),
    path("billing/<uuid:store_id>/", views.billing, name="billing"),
]
