"""
Template-based views for core application.
"""

from django.shortcuts import render
from django.http import JsonResponse


def home(request):
    """Home page with information."""
    return render(request, 'index.html')