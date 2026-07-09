"""
URL configuration for help app.
"""

from django.urls import path

from apps.common.views_placeholder import placeholder_view
from . import views
from . import admin_views

app_name = "help"

urlpatterns = [
    # Placeholder routes - update when implemented
    path("documentation/", placeholder_view, {"app_name": "Documentation"}, name="documentation"),

    # Support routes (public/user)
    path("", views.support_home, name="support"),
    path("faq/<slug:slug>/", views.faq_detail, name="faq_detail"),
    path("faq/search/", views.search_faqs, name="faq_search"),
    path("tickets/", views.my_tickets, name="my_tickets"),
    path("tickets/create/", views.create_ticket, name="create_ticket"),
    path("tickets/<str:ticket_id>/", views.ticket_detail, name="ticket_detail"),
    path("tickets/<str:ticket_id>/close/", views.close_ticket, name="close_ticket"),
    path("tickets/<str:ticket_id>/reopen/", views.reopen_ticket, name="reopen_ticket"),

    # Staff/Admin routes
    path("staff/", admin_views.staff_dashboard, name="staff_dashboard"),
    path("staff/queue/", admin_views.staff_tickets_queue, name="staff_tickets_queue"),
    path("staff/tickets/<str:ticket_id>/", admin_views.staff_ticket_detail, name="staff_ticket_detail"),
    path("staff/tickets/<str:ticket_id>/change-status/", admin_views.staff_change_status, name="staff_change_status"),
    path("staff/tickets/<str:ticket_id>/assign/", admin_views.staff_assign_ticket, name="staff_assign_ticket"),
    path("staff/tickets/<str:ticket_id>/internal-note/", admin_views.staff_internal_note, name="staff_internal_note"),
    path("staff/faq/", admin_views.faq_management, name="staff_faq_management"),
]