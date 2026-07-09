"""
Views for help and support functionality.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse_lazy
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import ensure_csrf_cookie
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.utils import timezone

from .models import SupportTicket, TicketComment, FAQCategory, FAQArticle
from .forms import SupportTicketForm, TicketCommentForm, FAQSearchForm


def support_home(request):
    """
    Main support page with FAQ and contact options.
    """
    # Get active FAQ categories with their articles
    categories = FAQCategory.objects.filter(
        is_active=True
    ).prefetch_related('articles').annotate(
        article_count=Count('articles')
    ).filter(article_count__gt=0).order_by('order')

    # Popular FAQs (most viewed)
    popular_faqs = FAQArticle.objects.filter(
        is_active=True
    ).order_by('-views')[:6]

    context = {
        'categories': categories,
        'popular_faqs': popular_faqs,
        'page_title': 'Support Center',
    }
    return render(request, 'help/support_home.html', context)


def faq_detail(request, slug):
    """
    Detailed FAQ article view.
    """
    article = get_object_or_404(FAQArticle, slug=slug, is_active=True)
    article.increment_view()

    # Get related articles from same category
    related_articles = FAQArticle.objects.filter(
        category=article.category,
        is_active=True
    ).exclude(pk=article.pk)[:5]

    context = {
        'article': article,
        'related_articles': related_articles,
        'page_title': f'FAQ: {article.question}',
    }
    return render(request, 'help/faq_detail.html', context)


@require_POST
def search_faqs(request):
    """
    AJAX FAQ search functionality.
    """
    form = FAQSearchForm(request.POST)
    results = []

    if form.is_valid():
        query = form.cleaned_data.get('q', '').strip()
        category = form.cleaned_data.get('category')

        articles = FAQArticle.objects.filter(is_active=True)

        if query:
            articles = articles.filter(
                Q(question__icontains=query) |
                Q(answer__icontains=query)
            )

        if category:
            articles = articles.filter(category=category)

        for article in articles[:10]:
            results.append({
                'title': article.question,
                'url': f"/help/faq/{article.slug}/",
                'category': article.category.name,
            })

    return JsonResponse({'results': results})


@login_required
def my_tickets(request):
    """
    User's support tickets list.
    """
    tickets = SupportTicket.objects.filter(
        user=request.user
    ).select_related('store').prefetch_related('comments')

    # Filter by status if provided
    status_filter = request.GET.get('status')
    if status_filter and status_filter != 'all':
        tickets = tickets.filter(status=status_filter)

    # Pagination
    paginator = Paginator(tickets, 10)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'status_filter': status_filter or 'all',
        'status_choices': SupportTicket.STATUS_CHOICES,
        'page_title': 'My Support Tickets',
    }
    return render(request, 'help/my_tickets.html', context)


@login_required
def create_ticket(request):
    """
    Create a new support ticket.
    """
    if request.method == 'POST':
        form = SupportTicketForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            ticket = form.save()
            messages.success(
                request,
                f'Support ticket {ticket.ticket_id} created successfully. '
                f'We\'ll respond within 24 hours.'
            )
            return redirect('help:ticket_detail', ticket_id=ticket.ticket_id)
    else:
        form = SupportTicketForm(user=request.user)

    context = {
        'form': form,
        'page_title': 'Create Support Ticket',
    }
    return render(request, 'help/create_ticket.html', context)


@login_required
def ticket_detail(request, ticket_id):
    """
    Support ticket detail view with comments.
    """
    ticket = get_object_or_404(
        SupportTicket,
        ticket_id=ticket_id,
        user=request.user
    )

    comments = ticket.comments.filter(is_internal=False).select_related('user')

    if request.method == 'POST':
        form = TicketCommentForm(request.POST, request.FILES)
        if form.is_valid():
            comment = TicketComment(
                ticket=ticket,
                user=request.user,
                content=form.cleaned_data['content'],
                is_staff_response=False
            )
            if form.cleaned_data.get('attachment'):
                comment.attachment = form.cleaned_data['attachment']
            comment.save()

            # Update ticket's last_response_from
            ticket.last_response_from = 'user'
            ticket.save(update_fields=['last_response_from'])

            messages.success(request, 'Your response has been added.')
            return redirect('help:ticket_detail', ticket_id=ticket.ticket_id)
    else:
        form = TicketCommentForm()

    context = {
        'ticket': ticket,
        'comments': comments,
        'form': form,
        'page_title': f'Ticket {ticket.ticket_id}',
    }
    return render(request, 'help/ticket_detail.html', context)


@login_required
@require_POST
def close_ticket(request, ticket_id):
    """
    Close a support ticket.
    """
    ticket = get_object_or_404(
        SupportTicket,
        ticket_id=ticket_id,
        user=request.user
    )

    if ticket.status != 'closed':
        ticket.status = 'closed'
        if not ticket.resolved_at:
            ticket.resolved_at = timezone.now()
        ticket.save(update_fields=['status', 'resolved_at'])
        messages.success(request, f'Ticket {ticket.ticket_id} has been closed.')

    return redirect('help:ticket_detail', ticket_id=ticket.ticket_id)


@login_required
@require_POST
def reopen_ticket(request, ticket_id):
    """
    Reopen a closed support ticket.
    """
    ticket = get_object_or_404(
        SupportTicket,
        ticket_id=ticket_id,
        user=request.user
    )

    if ticket.status == 'closed':
        ticket.status = 'open'
        ticket.resolved_at = None
        ticket.last_response_from = 'user'
        ticket.save(update_fields=['status', 'resolved_at', 'last_response_from'])
        messages.success(request, f'Ticket {ticket.ticket_id} has been reopened.')

    return redirect('help:ticket_detail', ticket_id=ticket.ticket_id)
