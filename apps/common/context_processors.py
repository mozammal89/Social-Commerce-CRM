"""
Custom context processors for Social Commerce CRM.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.db import models
from apps.stores.models import Store

User = get_user_model()


def app_settings(request):
    """Add application settings to all templates."""
    return {
        "APP_NAME": "Social Commerce CRM",
        "APP_VERSION": "1.0.0",
        "DEBUG": settings.DEBUG,
    }


def current_store(request):
    """Add current store context if available."""
    context = {
        "current_store": None,
        "user_stores": [],
    }
    
    if request.user.is_authenticated:
        user = request.user
        context["user_stores"] = Store.objects.filter(
            models.Q(owners=user) | 
            models.Q(managers=user) | 
            models.Q(staff=user)
        ).distinct()
        
        # Get current store from session or first available
        store_id = request.session.get("current_store_id")
        if store_id:
            try:
                context["current_store"] = Store.objects.get(
                    id=store_id,
                    is_deleted=False
                )
            except Store.DoesNotExist:
                pass
        
        # Set default store if none selected
        if not context["current_store"] and context["user_stores"].exists():
            context["current_store"] = context["user_stores"].first()
    
    return context