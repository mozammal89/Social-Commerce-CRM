"""
Placeholder views for CRM apps that return proper HttpResponse objects.

Bug 1 / Bug 15: these views previously had no auth check. Now they
require login. They are store-agnostic so a permission check is not
appropriate; ``@login_required`` is the right gate.
"""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render


@login_required
def placeholder_view(request, app_name="App"):
    """Placeholder view for apps not yet implemented."""
    return render(request, 'placeholder.html', {
        'app_name': app_name,
        'title': f'{app_name} - Coming Soon'
    })


@login_required
def coming_soon(request):
    """Generic coming soon page."""
    return render(request, 'placeholder.html', {
        'app_name': 'Feature',
        'title': 'Coming Soon'
    })
