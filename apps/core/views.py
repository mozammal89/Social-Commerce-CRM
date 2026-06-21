"""
Views for landing page.
"""

from django.shortcuts import render
from django.db import connections
from django.http import JsonResponse
from django.core.cache import cache
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from decimal import Decimal


def health_check(request):
    """Simple health check endpoint."""
    return JsonResponse(
        {
            "status": "healthy",
            "timestamp": timezone.now().isoformat(),
        }
    )


class DetailedHealthCheckView(APIView):
    """Detailed health check with service status."""

    permission_classes = []

    def get(self, request):
        """Return detailed health status."""
        health_status = {
            "status": "healthy",
            "timestamp": timezone.now().isoformat(),
            "services": {},
            "version": "1.0.0",
        }

        overall_healthy = True

        database_status = self.check_database()
        health_status["services"]["database"] = database_status
        if not database_status["healthy"]:
            overall_healthy = False

        redis_status = self.check_redis()
        health_status["services"]["redis"] = redis_status
        if not redis_status["healthy"]:
            overall_healthy = False

        celery_status = self.check_celery()
        health_status["services"]["celery"] = celery_status
        if not celery_status["healthy"]:
            overall_healthy = False

        health_status["status"] = "healthy" if overall_healthy else "unhealthy"

        status_code = 200 if overall_healthy else 503
        return Response(health_status, status=status_code)

    def check_database(self):
        """Check database connection."""
        try:
            db_conn = connections["default"]
            db_conn.cursor()
            return {
                "healthy": True,
                "message": "Database connection successful",
            }
        except Exception as e:
            return {
                "healthy": False,
                "message": f"Database connection failed: {str(e)}",
            }

    def check_redis(self):
        """Check Redis connection."""
        try:
            cache.set("health_check", "ok", 10)
            value = cache.get("health_check")
            if value == "ok":
                return {
                    "healthy": True,
                    "message": "Redis connection successful",
                }
            else:
                return {
                    "healthy": False,
                    "message": "Redis read/write failed",
                }
        except Exception as e:
            return {
                "healthy": False,
                "message": f"Redis connection failed: {str(e)}",
            }

    def check_celery(self):
        """Check Celery worker availability."""
        try:
            from celery import current_app

            inspector = current_app.control.inspect()
            stats = inspector.stats()

            if stats:
                return {
                    "healthy": True,
                    "message": f"Celery workers online: {len(stats)}",
                    "workers": list(stats.keys()),
                }
            else:
                return {
                    "healthy": False,
                    "message": "No Celery workers online",
                }
        except Exception as e:
            return {
                "healthy": False,
                "message": f"Celery check failed: {str(e)}",
            }


def landing_home(request):
    """
    Landing page with all sections and features.
    """
    from apps.permissions.models import SubscriptionPlan

    # Separate monthly and yearly plans
    monthly_plans = SubscriptionPlan.objects.filter(
        is_active=True, is_public=True, billing_period="monthly"
    ).order_by("sort_order", "price")

    yearly_plans = SubscriptionPlan.objects.filter(
        is_active=True, is_public=True, billing_period="yearly"
    ).order_by("sort_order", "price")

    context = {
        "monthly_plans": monthly_plans,
        "yearly_plans": yearly_plans,
    }

    return render(request, "landing/home.html", context)
