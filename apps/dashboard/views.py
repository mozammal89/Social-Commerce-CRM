"""
Template-based views for dashboard.
"""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import models

from apps.stores.models import Store


@login_required
def dashboard_home(request):
    """Dashboard home view."""
    user = request.user
    
    # Get user's stores
    user_stores = Store.objects.filter(
        models.Q(owners=user) | 
        models.Q(managers=user) | 
        models.Q(staff=user)
    ).distinct()
    
    # Get current store from session or first available
    current_store = None
    store_id = request.session.get("current_store_id")
    if store_id:
        try:
            current_store = Store.objects.get(id=store_id, is_deleted=False)
        except Store.DoesNotExist:
            pass
    
    # Set default store if none selected
    if not current_store and user_stores.exists():
        current_store = user_stores.first()
        if current_store:
            request.session['current_store_id'] = str(current_store.id)
    
    context = {
        'user': user,
        'current_store': current_store,
        'user_stores': user_stores,
    }
    return render(request, 'dashboard/index.html', context)


@login_required
def switch_store(request, store_id):
    """Switch the current store for the session."""
    from apps.stores.models import Store
    
    user = request.user
    try:
        store = Store.objects.get(id=store_id)
        
        if not store.has_user_access(user):
            messages.error(request, "You don't have access to this store.")
            return redirect('dashboard:home')
        
        request.session['current_store_id'] = str(store_id)
        messages.success(request, f"Switched to store: {store.name}")
        
        return redirect('dashboard:home')
        
    except Store.DoesNotExist:
        messages.error(request, "Store not found.")
        return redirect('dashboard:home')