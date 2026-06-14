"""
URL configuration for accounts app.

This file contains both API and template-based URL patterns.
"""

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

# API Views
from apps.accounts.views import (
    RegisterView,
    CustomTokenObtainPairView,
    UserProfileView,
    ChangePasswordView,
    user_me,
    logout,
)

# Template Views
from apps.accounts.views_template import (
    LoginView as TemplateLoginView,
    RegistrationView as TemplateRegisterView,
    LogoutView as TemplateLogoutView,
    profile as TemplateProfileView,
    avatar_upload as TemplateAvatarUploadView,
    CustomPasswordChangeView as TemplateChangePasswordView,
    CustomPasswordResetView as TemplatePasswordResetView,
    CustomPasswordResetConfirmView as TemplatePasswordResetConfirmView,
    CustomPasswordResetDoneView as TemplatePasswordResetDoneView,
    CustomPasswordResetCompleteView as TemplatePasswordResetCompleteView,
    change_password_done as TemplateChangePasswordDoneView,
)
from apps.common.views_placeholder import placeholder_view

app_name = "accounts"

# API URL Patterns
api_urlpatterns = [
    path("register/", RegisterView.as_view(), name="api_register"),
    path("login/", CustomTokenObtainPairView.as_view(), name="api_login"),
    path("token/refresh/", TokenRefreshView.as_view(), name="api_token_refresh"),
    path("logout/", logout, name="api_logout"),
    path("me/", user_me, name="api_user_me"),
    path("profile/", UserProfileView.as_view(), name="api_profile"),
    path("change-password/", ChangePasswordView.as_view(), name="api_change_password"),
]

# Template URL Patterns
template_urlpatterns = [
    path("login/", TemplateLoginView.as_view(), name="login"),
    path("register/", TemplateRegisterView.as_view(), name="register"),
    path("logout/", TemplateLogoutView.as_view(), name="logout"),
    path("profile/", TemplateProfileView, name="profile"),
    path("profile/settings/", placeholder_view, {"app_name": "Profile Settings"}, name="profile_settings"),
    path("profile/avatar/", TemplateAvatarUploadView, name="avatar"),
    path("change-password/", TemplateChangePasswordView.as_view(), name="change_password"),
    path("change-password/done/", TemplateChangePasswordDoneView, name="change_password_done"),
    path("password-reset/", TemplatePasswordResetView.as_view(), name="password_reset"),
    path("password-reset/done/", TemplatePasswordResetDoneView.as_view(), name="password_reset_done"),
    path("password-reset/confirm/<uidb64>/<token>/", TemplatePasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("password-reset/complete/", TemplatePasswordResetCompleteView.as_view(), name="password_reset_complete"),
]

# For main auth routes, use template patterns
urlpatterns = template_urlpatterns