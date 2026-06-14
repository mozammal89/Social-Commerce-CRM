"""
Template URL configuration for accounts app.
"""

from django.urls import path
from apps.accounts.views_template import (
    LoginView as TemplateLoginView,
    RegistrationView as TemplateRegisterView,
    LogoutView as TemplateLogoutView,
    profile as TemplateProfileView,
    CustomPasswordChangeView as TemplateChangePasswordView,
    CustomPasswordResetView as TemplatePasswordResetView,
    CustomPasswordResetConfirmView as TemplatePasswordResetConfirmView,
    CustomPasswordResetDoneView as TemplatePasswordResetDoneView,
    CustomPasswordResetCompleteView as TemplatePasswordResetCompleteView,
    change_password_done as TemplateChangePasswordDoneView,
)
from apps.common.views_placeholder import placeholder_view

app_name = "accounts"

urlpatterns = [
    path("login/", TemplateLoginView.as_view(), name="login"),
    path("register/", TemplateRegisterView.as_view(), name="register"),
    path("logout/", TemplateLogoutView.as_view(), name="logout"),
    path("profile/", TemplateProfileView, name="profile"),
    path("profile/settings/", placeholder_view, {"app_name": "Profile Settings"}, name="profile_settings"),
    path("profile/avatar/", placeholder_view, {"app_name": "Avatar Upload"}, name="avatar"),
    path("change-password/", TemplateChangePasswordView.as_view(), name="change_password"),
    path("change-password/done/", TemplateChangePasswordDoneView, name="change_password_done"),
    path("password-reset/", TemplatePasswordResetView.as_view(), name="password_reset"),
    path("password-reset/done/", TemplatePasswordResetDoneView.as_view(), name="password_reset_done"),
    path("password-reset/confirm/<uidb64>/<token>/", TemplatePasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("password-reset/complete/", TemplatePasswordResetCompleteView.as_view(), name="password_reset_complete"),
]