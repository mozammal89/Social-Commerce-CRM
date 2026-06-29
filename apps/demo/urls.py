from django.urls import path
from .views import (
    advanced_analytics_view,
    export_analytics_view,
    realtime_dashboard_view,
    manage_integrations_view,
    bulk_customers_view,
    permission_test_view,
    api_analytics_summary,
    api_analytics_export,
    custom_decorator_view,
)

urlpatterns = [
    # Demo RBAC Views
    path("demo/advanced-analytics/", advanced_analytics_view, name="demo_advanced_analytics"),
    path("demo/export-analytics/", export_analytics_view, name="demo_export_analytics"),
    path("demo/realtime-dashboard/", realtime_dashboard_view, name="demo_realtime_dashboard"),
    path("demo/manage-integrations/", manage_integrations_view, name="demo_manage_integrations"),
    path("demo/bulk-customers/", bulk_customers_view, name="demo_bulk_customers"),
    path("demo/permission-test/", permission_test_view, name="demo_permission_test"),
    path("demo/custom-decorator/", custom_decorator_view, name="demo_custom_decorator"),
    # Demo API Endpoints
    path("api/analytics/summary/", api_analytics_summary, name="api_analytics_summary"),
    path("api/analytics/export/", api_analytics_export, name="api_analytics_export"),
]
