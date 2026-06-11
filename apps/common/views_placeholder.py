"""
Placeholder views for CRM apps that return proper HttpResponse objects.
"""

from django.http import HttpResponse
from django.shortcuts import render


def placeholder_view(request, app_name="App"):
    """Placeholder view for apps not yet implemented."""
    return render(request, 'placeholder.html', {
        'app_name': app_name,
        'title': f'{app_name} - Coming Soon'
    })


def coming_soon(request):
    """Generic coming soon page."""
    return render(request, 'placeholder.html', {
        'app_name': 'Feature',
        'title': 'Coming Soon'
    })