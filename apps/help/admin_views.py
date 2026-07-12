"""
Admin and staff views for managing support tickets.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.utils import timezone

from .models import SupportTicket, TicketComment, FAQCategory, FAQArticle
from .forms import TicketCommentForm


def is_staff_or_superuser(user):
    """Check if user is staff or superuser."""
    return user.is_staff or user.is_superuser


@login_required
@user_passes_test(is_staff_or_superuser, login_url='/dashboard/', redirect_field_name=None)
def staff_dashboard(request):
    """
    Staff support dashboard with ticket statistics and queue.
    """
    # Get statistics
    stats = {
        'total': SupportTicket.objects.count(),
        'open': SupportTicket.objects.filter(status='open').count(),
        'in_progress': SupportTicket.objects.filter(status='in_progress').count(),
        'pending': SupportTicket.objects.filter(status='pending').count(),
        'resolved': SupportTicket.objects.filter(status='resolved').count(),
        'closed': SupportTicket.objects.filter(status='closed').count(),
    }

    # Get recent tickets
    tickets = SupportTicket.objects.select_related('user', 'store').prefetch_related('comments').order_by('-created_at')[:20]

    # Get urgent tickets (high priority and not closed)
    urgent_tickets = SupportTicket.objects.filter(
        priority__in=['high', 'urgent'],
        status__in=['open', 'in_progress']
    ).select_related('user', 'store').order_by('-created_at')[:10]

    context = {
        'stats': stats,
        'recent_tickets': tickets,
        'urgent_tickets': urgent_tickets,
        'page_title': 'Support Dashboard',
    }
    return render(request, 'help/staff/dashboard.html', context)


@login_required
@user_passes_test(is_staff_or_superuser, login_url='/dashboard/', redirect_field_name=None)
def staff_tickets_queue(request):
    """
    Staff tickets queue with filtering and pagination.
    """
    tickets = SupportTicket.objects.select_related('user', 'store').prefetch_related('comments')

    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter:
        tickets = tickets.filter(status=status_filter)

    # Filter by priority
    priority_filter = request.GET.get('priority', '')
    if priority_filter:
        tickets = tickets.filter(priority=priority_filter)

    # Filter by category
    category_filter = request.GET.get('category', '')
    if category_filter:
        tickets = tickets.filter(category=category_filter)

    # Search
    search_query = request.GET.get('q', '')
    if search_query:
        tickets = tickets.filter(
            Q(ticket_id__icontains=search_query) |
            Q(subject__icontains=search_query) |
            Q(user__email__icontains=search_query)
        )

    # Sorting
    sort_by = request.GET.get('sort', '-created_at')
    tickets = tickets.order_by(sort_by)

    # Pagination
    paginator = Paginator(tickets, 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'status_filter': status_filter,
        'priority_filter': priority_filter,
        'category_filter': category_filter,
        'search_query': search_query,
        'sort_by': sort_by,
        'status_choices': SupportTicket.STATUS_CHOICES,
        'priority_choices': SupportTicket.PRIORITY_CHOICES,
        'category_choices': SupportTicket.CATEGORY_CHOICES,
        'page_title': 'Tickets Queue',
    }
    return render(request, 'help/staff/tickets_queue.html', context)


@login_required
@user_passes_test(is_staff_or_superuser, login_url='/dashboard/', redirect_field_name=None)
def staff_ticket_detail(request, ticket_id):
    """
    Staff view for ticket detail with ability to respond.
    """
    ticket = get_object_or_404(SupportTicket, ticket_id=ticket_id)
    comments = ticket.comments.filter(is_internal=False).select_related('user')

    if request.method == 'POST':
        form = TicketCommentForm(request.POST, request.FILES)
        if form.is_valid():
            comment = TicketComment(
                ticket=ticket,
                user=request.user,
                content=form.cleaned_data['content'],
                is_staff_response=True
            )
            if form.cleaned_data.get('attachment'):
                comment.attachment = form.cleaned_data['attachment']
            comment.save()

            # Update ticket status and last_response_from
            ticket.last_response_from = 'support'
            ticket.save(update_fields=['last_response_from'])

            messages.success(request, f'Response added to ticket {ticket.ticket_id}.')

            # Handle status change
            new_status = request.POST.get('change_status')
            if new_status and new_status != ticket.status:
                ticket.status = new_status
                if new_status == 'resolved' and not ticket.resolved_at:
                    ticket.resolved_at = timezone.now()
                ticket.save()
                messages.info(request, f'Ticket status changed to {ticket.get_status_display()}.')

            return redirect('help:staff_ticket_detail', ticket_id=ticket.ticket_id)
    else:
        form = TicketCommentForm()

    context = {
        'ticket': ticket,
        'comments': comments,
        'form': form,
        'status_choices': SupportTicket.STATUS_CHOICES,
        'page_title': f'Ticket {ticket.ticket_id}',
    }
    return render(request, 'help/staff/ticket_detail.html', context)


@login_required
@user_passes_test(is_staff_or_superuser, login_url='/dashboard/', redirect_field_name=None)
def staff_change_status(request, ticket_id):
    """
    Quick status change for staff.
    """
    ticket = get_object_or_404(SupportTicket, ticket_id=ticket_id)

    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status and new_status in dict(SupportTicket.STATUS_CHOICES):
            ticket.status = new_status
            if new_status == 'resolved' and not ticket.resolved_at:
                ticket.resolved_at = timezone.now()
            elif new_status != 'resolved':
                ticket.resolved_at = None
            ticket.save()
            messages.success(request, f'Ticket {ticket.ticket_id} status changed to {ticket.get_status_display()}.')
        else:
            messages.error(request, 'Invalid status.')

    return redirect(request.META.get('HTTP_REFERER', 'help:staff_tickets_queue'))


@login_required
@user_passes_test(is_staff_or_superuser, login_url='/dashboard/', redirect_field_name=None)
def staff_assign_ticket(request, ticket_id):
    """
    Assign a ticket to a staff member (yourself for now).
    """
    ticket = get_object_or_404(SupportTicket, ticket_id=ticket_id)

    if request.method == 'POST':
        ticket.assigned_to = request.user
        ticket.status = 'in_progress'
        ticket.save(update_fields=['assigned_to', 'status'])
        messages.success(request, f'Ticket {ticket.ticket_id} has been assigned to you.')

    return redirect('help:staff_ticket_detail', ticket_id=ticket_id)


@login_required
@user_passes_test(is_staff_or_superuser, login_url='/dashboard/', redirect_field_name=None)
def staff_internal_note(request, ticket_id):
    """
    Add internal note (visible only to staff).
    """
    ticket = get_object_or_404(SupportTicket, ticket_id=ticket_id)

    if request.method == 'POST':
        content = request.POST.get('content', '').strip()
        if content:
            TicketComment.objects.create(
                ticket=ticket,
                user=request.user,
                content=content,
                is_staff_response=True,
                is_internal=True
            )
            messages.success(request, 'Internal note added.')

    return redirect('help:staff_ticket_detail', ticket_id=ticket_id)


@login_required
@user_passes_test(is_staff_or_superuser, login_url='/dashboard/', redirect_field_name=None)
def faq_management(request):
    """
    FAQ management for staff.
    """
    categories = FAQCategory.objects.filter(is_active=True).prefetch_related('articles')
    articles = FAQArticle.objects.select_related('category').order_by('-views')[:50]

    context = {
        'categories': categories,
        'articles': articles,
        'page_title': 'FAQ Management',
    }
    return render(request, 'help/staff/faq_management.html', context)
