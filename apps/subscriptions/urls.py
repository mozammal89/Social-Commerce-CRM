from django.urls import path
from . import views
from . import api_views

app_name = "subscriptions"

urlpatterns = [
    # Template views
    path("plans/", views.subscription_plans, name="plans"),
    path("checkout/<slug:plan_slug>/", views.subscription_checkout, name="checkout"),
    path("welcome/", views.subscription_welcome, name="welcome"),
    path("success/", views.subscription_success, name="success"),
    path("manage/", views.manage_subscription, name="manage"),
    # API views
    path("api/plans/", views.PlanListView.as_view(), name="api-plans"),
    path("api/plans/<slug:slug>/", views.PlanDetailView.as_view(), name="api-plan-detail"),
    path("api/create/", views.create_subscription, name="api-create"),
    path("api/cancel/", views.cancel_subscription_view, name="api-cancel"),
    path(
        "api/reactivate/",
        views.reactivate_subscription_view,
        name="api-reactivate",
    ),
    path("api/update-plan/", views.update_subscription_plan, name="api-update-plan"),
    path("api/current/", views.get_current_subscription, name="api-current"),
    path("api/limits/", views.check_subscription_limits, name="api-limits"),
    # Aggregated API views (for multi-store support)
    path("api/aggregated-limits/", api_views.get_aggregated_limits, name="api-aggregated-limits"),
]
