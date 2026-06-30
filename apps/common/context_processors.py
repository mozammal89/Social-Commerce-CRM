"""
Custom context processors for Social Commerce CRM.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.db import models
from django.urls import reverse
from apps.stores.models import Store

User = get_user_model()


def breadcrumbs(request):
    """
    Automatically generate breadcrumbs based on the current URL.

    This context processor analyzes the current URL pattern and builds
    appropriate breadcrumbs without requiring manual configuration in each view.
    """
    breadcrumbs = []
    resolver_match = getattr(request, 'resolver_match', None)

    if not resolver_match:
        return {'breadcrumbs': breadcrumbs}

    # Define breadcrumb mappings for different URL patterns
    # Format: 'app_name:url_name' -> [breadcrumb_items]
    breadcrumb_map = {
        'dashboard:home': [],  # Just home, no additional breadcrumbs

        # Stores breadcrumbs
        'stores:store_list_html': [{'title': 'My Stores', 'url': reverse('stores:store_list_html')}],
        'stores:create': [
            {'title': 'My Stores', 'url': reverse('stores:store_list_html')},
            {'title': 'Create Store', 'url': ''},
        ],

        # Products breadcrumbs
        'products:list': [
            {'title': 'Products', 'url': reverse('products:list')},
        ],
        'products:create': [
            {'title': 'Products', 'url': reverse('products:list')},
            {'title': 'Create Product', 'url': ''},
        ],

        # Orders breadcrumbs
        'orders:list': [
            {'title': 'Orders', 'url': reverse('orders:list')},
        ],
        'orders:create': [
            {'title': 'Orders', 'url': reverse('orders:list')},
            {'title': 'Create Order', 'url': ''},
        ],

        # Customers breadcrumbs
        'customers:list': [
            {'title': 'Customers', 'url': reverse('customers:list')},
        ],
        'customers:create': [
            {'title': 'Customers', 'url': reverse('customers:list')},
            {'title': 'Add Customer', 'url': ''},
        ],

        # Settings breadcrumbs
        'settings:store': [{'title': 'Settings', 'url': '#'}],
        'settings:integrations': [
            {'title': 'Settings', 'url': '#'},
            {'title': 'Integrations', 'url': ''},
        ],
        'settings:billing': [
            {'title': 'Settings', 'url': '#'},
            {'title': 'Billing', 'url': ''},
        ],

        # Account breadcrumbs
        'accounts:profile': [{'title': 'Account', 'url': '#'}],
        'accounts:change_password': [
            {'title': 'Account', 'url': '#'},
            {'title': 'Change Password', 'url': ''},
        ],

        # Help breadcrumbs
        'help:documentation': [{'title': 'Help', 'url': '#'}],
        'help:support': [{'title': 'Help', 'url': '#'}, {'title': 'Support', 'url': ''}],
    }

    # Get the base URL pattern
    url_pattern = f"{resolver_match.app_name}:{resolver_match.url_name}" if resolver_match.app_name else resolver_match.url_name

    # Get base breadcrumbs from map
    base_breadcrumbs = breadcrumb_map.get(url_pattern, [])

    # Handle dynamic pages that need additional data
    if url_pattern == 'stores:store_detail_html':
        # Store detail - add store name
        breadcrumbs = base_breadcrumbs.copy()
        # Try to get store from URL kwargs
        store_id = resolver_match.kwargs.get('store_id')
        if store_id:
            try:
                from apps.stores.models import Store
                store = Store.objects.filter(id=store_id, is_deleted=False).first()
                if store:
                    breadcrumbs.append({'title': store.name, 'url': ''})
                else:
                    breadcrumbs.append({'title': 'Store Details', 'url': ''})
            except:
                breadcrumbs.append({'title': 'Store Details', 'url': ''})
        else:
            breadcrumbs.append({'title': 'Store Details', 'url': ''})

    elif url_pattern == 'stores:store_edit_html':
        # Store edit - add store name and Edit
        breadcrumbs = base_breadcrumbs.copy()
        store_id = resolver_match.kwargs.get('store_id')
        if store_id:
            try:
                from apps.stores.models import Store
                store = Store.objects.filter(id=store_id, is_deleted=False).first()
                if store:
                    breadcrumbs.append({'title': store.name, 'url': reverse('stores:store_detail_html', args=[store.id])})
                    breadcrumbs.append({'title': 'Edit', 'url': ''})
                else:
                    breadcrumbs.append({'title': 'Edit Store', 'url': ''})
            except:
                breadcrumbs.append({'title': 'Edit Store', 'url': ''})
        else:
            breadcrumbs.append({'title': 'Edit Store', 'url': ''})

    else:
        # Use base breadcrumbs as is
        breadcrumbs = base_breadcrumbs

    return {'breadcrumbs': breadcrumbs}


def _get_user_subscription_context(user):
    """
    Get subscription-related context for a user.

    Returns a dict with:
    - user_subscription: active subscription object or None
    - has_user_subscription: boolean
    - has_pending_subscription: boolean
    - pending_plan: plan object if pending or None
    """
    context = {
        "user_subscription": None,
        "has_user_subscription": False,
        "has_pending_subscription": False,
        "pending_plan": None,
    }

    if not user or not user.is_authenticated:
        return context

    # Check if user has existing subscriptions (regardless of pending plan)
    try:
        from apps.permissions.models import Subscription

        user_subscription = (
            Subscription.objects.filter(
                store__memberships__user=user,
                store__memberships__is_active=True,
                status__in=["trialing", "active"],
            )
            .select_related("plan")
            .first()
        )

        if user_subscription:
            context["user_subscription"] = user_subscription
            context["has_user_subscription"] = True
    except Exception:
        pass

    # Check for pending subscription (user subscribed but no store yet, or upgrading plan)
    if user.pending_plan_slug:
        context["has_pending_subscription"] = True
        try:
            from apps.permissions.models import SubscriptionPlan

            pending_plan = SubscriptionPlan.objects.get(slug=user.pending_plan_slug)
            context["pending_plan"] = pending_plan
        except SubscriptionPlan.DoesNotExist:
            pass

    return context


def app_settings(request):
    """Add application settings to all templates."""
    return {
        "APP_NAME": "Social Commerce CRM",
        "APP_VERSION": "1.0.0",
        "DEBUG": settings.DEBUG,
    }


def current_store(request):
    """Add current store and subscription context to all templates.

    Bug 2 / Bug 15 fix: this used to query the legacy M2M (owners /
    managers / staff) and would return stores the user no longer has an
    active membership for. It now consults ``StoreMembership`` (active
    rows only), matching the resolution order used by the new
    ``@current_store`` decorator (session → first available).

    Super Admin Fix: Superusers should see all stores regardless of
    membership, allowing them to switch between any store in the system.

    Subscription Context: Also provides subscription-related context
    globally so the sidebar can show "Create Store" menu consistently
    across all pages.
    """
    context = {
        "current_store": None,
        "user_stores": [],
    }

    if not getattr(request.user, "is_authenticated", False):
        return context

    user = request.user

    # Super Admin: Show all stores regardless of membership
    if user.is_superuser:
        context["user_stores"] = list(
            Store.objects.filter(
                is_deleted=False,
            ).order_by("name")
        )
    else:
        # Regular user: Only show stores with active membership
        context["user_stores"] = list(
            Store.objects.filter(
                memberships__user=user,
                memberships__is_active=True,
                is_deleted=False,
            )
            .distinct()
            .order_by("name")
        )

    # Get current store from session or first available
    store_id = request.session.get("current_store_id")
    if store_id:
        for s in context["user_stores"]:
            if str(s.id) == str(store_id):
                context["current_store"] = s
                break

    # Set default store if none selected
    if not context["current_store"] and context["user_stores"]:
        context["current_store"] = context["user_stores"][0]

    # Add subscription-related context
    context.update(_get_user_subscription_context(user))
    # Add user_has_no_store flag for templates
    context["user_has_no_store"] = len(context["user_stores"]) == 0

    return context
