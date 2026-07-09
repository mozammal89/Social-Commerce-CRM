"""
URL configuration for the omnichannel messaging app.

The unified inbox, channels and customers features are implemented in
later phases. These routes currently point at module-specific
"coming soon" views so the sidebar links resolve and can be tested.

Namespacing follows the project convention: ``app_name = "messaging"``
and routes are reversed as ``{% url 'messaging:inbox' %}`` etc.
"""

from django.urls import path

from . import views

app_name = "messaging"

urlpatterns = [
    path("inbox/", views.inbox, name="inbox"),
    path("channels/", views.channels, name="channels"),
    path("customers/", views.customers, name="customers"),
]
