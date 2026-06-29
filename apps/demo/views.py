"""
Demo Views to demonstrate RBAC system workflow

These views showcase different permission patterns and the complete
process of adding, syncing, and testing permissions.
"""

from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import permission_required, login_required
from django.core.exceptions import PermissionDenied

from apps.permissions.decorators import check_permission
from apps.permissions.services import user_has_permission


# DEMO 1: Advanced Analytics View
# This demonstrates a new permission that doesn't exist in the system yet
@permission_required("analytics.advanced_reports", raise_exception=True)
@login_required
def advanced_analytics_view(request):
    """
    Advanced analytics dashboard with detailed metrics.
    Permission required: analytics.advanced_reports
    """
    # This permission doesn't exist yet in our system
    # We'll use it to demonstrate the sync process

    data = {
        "title": "Advanced Analytics",
        "metrics": {
            "total_revenue": 125000.50,
            "conversion_rate": 3.2,
            "customer_lifetime_value": 850.00,
            "repeat_purchase_rate": 45.8,
        },
        "charts": [
            {"type": "line", "name": "Revenue Trend"},
            {"type": "bar", "name": "Top Products"},
            {"type": "pie", "name": "Customer Segments"},
        ],
        "permission": "analytics.advanced_reports",
    }

    return render(request, "demo/advanced_analytics.html", {"data": data})


# DEMO 2: Analytics Export View
# Another new permission to demonstrate syncing multiple permissions
@check_permission("analytics.export", raise_exception=True)
@login_required
def export_analytics_view(request):
    """
    Export analytics data in various formats.
    Permission required: analytics.export
    """
    # Another new permission that will need to be synced

    export_data = {
        "date_range": "2024-01-01 to 2024-12-31",
        "format": request.GET.get("format", "csv"),
        "data": [
            {"month": "January", "revenue": 12000},
            {"month": "February", "revenue": 15000},
            {"month": "March", "revenue": 18000},
            # ... more data
        ],
    }

    response = JsonResponse(export_data)
    response["Content-Disposition"] = 'attachment; filename="analytics_export.json"'
    return response


# DEMO 3: Real-time Dashboard View
# Demonstrates a view with multiple permission checks
@login_required
def realtime_dashboard_view(request):
    """
    Real-time dashboard with conditional features based on permissions.
    Demonstrates dynamic permission-based UI rendering.
    """
    store = request.store

    # Check multiple permissions for different features
    has_advanced = user_has_permission(request.user, store, "analytics.advanced_reports")
    has_export = user_has_permission(request.user, store, "analytics.export")
    has_live_data = user_has_permission(request.user, store, "analytics.live_data")

    features = {
        "basic_dashboard": True,  # Everyone has access
        "advanced_analytics": has_advanced,
        "export_data": has_export,
        "live_updates": has_live_data,
    }

    data = {
        "title": "Real-time Dashboard",
        "features": features,
        "metrics": {"active_users": 45, "live_orders": 12, "revenue_today": 3200.50},
        "permissions": {
            "analytics.advanced_reports": has_advanced,
            "analytics.export": has_export,
            "analytics.live_data": has_live_data,
        },
    }

    return render(request, "demo/realtime_dashboard.html", {"data": data})


# DEMO 4: Sensitive Operations View
# Demonstrates high-security permission requirements
@permission_required("system.integrations", raise_exception=True)
@login_required
def manage_integrations_view(request):
    """
    Manage third-party integrations (high security).
    Permission required: system.integrations
    """
    # Another new permission for demonstration

    integrations = [
        {"name": "Facebook", "status": "connected", "last_sync": "2024-01-15"},
        {"name": "WhatsApp", "status": "disconnected", "last_sync": "2024-01-10"},
        {"name": "Payment Gateway", "status": "connected", "last_sync": "2024-01-15"},
    ]

    data = {
        "title": "Integration Management",
        "integrations": integrations,
        "permission": "system.integrations",
    }

    return render(request, "demo/manage_integrations.html", {"data": data})


# DEMO 5: Bulk Operations View
# Demonstrates permission for bulk/sensitive operations
@check_permission("customers.bulk_operations", raise_exception=True)
@login_required
def bulk_customers_view(request):
    """
    Bulk customer operations (import/export/delete in bulk).
    Permission required: customers.bulk_operations
    """
    # New permission for bulk operations

    data = {
        "title": "Bulk Customer Operations",
        "operations": [
            {"name": "Import Customers", "endpoint": "/api/customers/import"},
            {"name": "Export Customers", "endpoint": "/api/customers/export"},
            {"name": "Bulk Delete", "endpoint": "/api/customers/bulk-delete"},
            {"name": "Bulk Update", "endpoint": "/api/customers/bulk-update"},
        ],
        "permission": "customers.bulk_operations",
        "warnings": [
            "These operations cannot be undone",
            "Always export data before bulk operations",
            "Test with small batches first",
        ],
    }

    return render(request, "demo/bulk_customers.html", {"data": data})


# DEMO 6: Permission Test Helper
# Helper view to test permissions dynamically
@login_required
def permission_test_view(request):
    """
    Test various permissions for the current user.
    Useful for debugging and verifying permission setups.
    """
    store = request.store
    user = request.user

    # List of permissions to test
    test_permissions = [
        # Existing permissions (should work)
        "customers.view",
        "orders.view",
        "dashboard.view",
        # New permissions we're adding (will fail initially)
        "analytics.advanced_reports",
        "analytics.export",
        "analytics.live_data",
        "system.integrations",
        "customers.bulk_operations",
    ]

    results = {}
    for perm_code in test_permissions:
        results[perm_code] = user_has_permission(user, store, perm_code)

    data = {
        "title": "Permission Test Dashboard",
        "user": user.email,
        "store": store.name if store else "No store",
        "results": results,
        "statistics": {
            "total": len(test_permissions),
            "granted": sum(1 for v in results.values() if v),
            "denied": sum(1 for v in results.values() if not v),
        },
    }

    return render(request, "demo/permission_test.html", {"data": data})


# DEMO 7: API Endpoints with Permissions
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
import json


@require_http_methods(["GET"])
@permission_required("analytics.advanced_reports", raise_exception=True)
@login_required
def api_analytics_summary(request):
    """API endpoint for analytics summary."""
    summary = {
        "total_revenue": 125000.50,
        "total_orders": 1250,
        "avg_order_value": 100.00,
        "conversion_rate": 3.2,
    }
    return JsonResponse(summary)


@require_http_methods(["POST"])
@check_permission("analytics.export", raise_exception=True)
@login_required
@csrf_exempt
def api_analytics_export(request):
    """API endpoint to trigger analytics export."""
    try:
        data = json.loads(request.body)
        export_format = data.get("format", "csv")

        # Simulate export creation
        export_id = f"export_{hash(str(data))}"

        return JsonResponse(
            {
                "status": "success",
                "export_id": export_id,
                "format": export_format,
                "download_url": f"/api/exports/{export_id}",
            }
        )
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)


# DEMO 8: Decorator Demonstration Views
from functools import wraps


def custom_permission_required(permission_code):
    """Custom decorator to demonstrate permission checking."""

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            store = request.store
            if not user_has_permission(request.user, store, permission_code):
                raise PermissionDenied(f"Permission required: {permission_code}")
            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator


@custom_permission_required("analytics.advanced_reports")
@login_required
def custom_decorator_view(request):
    """View using custom permission decorator."""
    return render(
        request,
        "demo/custom_decorator.html",
        {
            "title": "Custom Decorator Demo",
            "message": "This view uses a custom permission decorator",
        },
    )
