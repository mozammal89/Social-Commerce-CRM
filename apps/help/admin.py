"""
Admin configuration for help and support models.
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from django.db.models import Count

from .models import SupportTicket, TicketComment, FAQCategory, FAQArticle


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    """Admin interface for support tickets."""

    list_display = [
        'ticket_id_display',
        'subject',
        'user_email',
        'category_display',
        'priority_display',
        'status_display',
        'created_at',
        'last_response_from'
    ]
    list_filter = ['status', 'priority', 'category', 'created_at']
    search_fields = ['ticket_id', 'subject', 'user__email', 'description']
    readonly_fields = ['ticket_id', 'created_at', 'updated_at']
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Ticket Information', {
            'fields': ('ticket_id', 'user', 'store', 'subject')
        }),
        ('Classification', {
            'fields': ('category', 'priority', 'status')
        }),
        ('Details', {
            'fields': ('description', 'attachment')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at', 'resolved_at', 'last_response_from')
        }),
    )

    def ticket_id_display(self, obj):
        return format_html('<span style="font-family: monospace;">{}</span>', obj.ticket_id)
    ticket_id_display.short_description = 'Ticket ID'

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'User'

    def category_display(self, obj):
        colors = {
            'technical': 'primary',
            'billing': 'info',
            'feature': 'success',
            'bug': 'danger',
            'account': 'warning',
            'integration': 'secondary',
            'other': 'dark'
        }
        color = colors.get(obj.category, 'secondary')
        return format_html('<span class="badge bg-{}">{}</span>', color, obj.get_category_display())
    category_display.short_description = 'Category'

    def priority_display(self, obj):
        colors = {
            'low': 'success',
            'medium': 'info',
            'high': 'warning',
            'urgent': 'danger'
        }
        color = colors.get(obj.priority, 'secondary')
        return format_html('<span class="badge bg-{}">{}</span>', color, obj.get_priority_display())
    priority_display.short_description = 'Priority'

    def status_display(self, obj):
        colors = {
            'open': 'primary',
            'in_progress': 'info',
            'pending': 'warning',
            'resolved': 'success',
            'closed': 'secondary'
        }
        color = colors.get(obj.status, 'secondary')
        return format_html('<span class="badge bg-{}">{}</span>', color, obj.get_status_display())
    status_display.short_description = 'Status'


@admin.register(TicketComment)
class TicketCommentAdmin(admin.ModelAdmin):
    """Admin interface for ticket comments."""

    list_display = ['ticket_id', 'user_email', 'is_staff_response', 'content_preview', 'created_at']
    list_filter = ['is_staff_response', 'is_internal', 'created_at']
    search_fields = ['ticket__ticket_id', 'user__email', 'content']
    readonly_fields = ['created_at']

    def ticket_id(self, obj):
        return obj.ticket.ticket_id
    ticket_id.short_description = 'Ticket'

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'User'

    def content_preview(self, obj):
        max_length = 50
        if len(obj.content) > max_length:
            return obj.content[:max_length] + '...'
        return obj.content
    content_preview.short_description = 'Comment'


@admin.register(FAQCategory)
class FAQCategoryAdmin(admin.ModelAdmin):
    """Admin interface for FAQ categories."""

    list_display = ['name', 'slug', 'article_count', 'is_active', 'order']
    list_filter = ['is_active']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ['order', 'is_active']

    def article_count(self, obj):
        return obj.articles.filter(is_active=True).count()
    article_count.short_description = 'Active Articles'


@admin.register(FAQArticle)
class FAQArticleAdmin(admin.ModelAdmin):
    """Admin interface for FAQ articles."""

    list_display = ['question', 'category', 'order', 'views', 'is_active', 'created_at']
    list_filter = ['category', 'is_active', 'created_at']
    search_fields = ['question', 'answer']
    prepopulated_fields = {'slug': ('question',)}
    readonly_fields = ['views', 'created_at', 'updated_at']
    list_editable = ['order', 'is_active']

    fieldsets = (
        ('Content', {
            'fields': ('category', 'question', 'answer', 'slug')
        }),
        ('Settings', {
            'fields': ('order', 'is_active')
        }),
        ('Metadata', {
            'fields': ('views', 'created_at', 'updated_at')
        }),
    )
