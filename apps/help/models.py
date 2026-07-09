"""
Models for help and support functionality.
"""

from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinLengthValidator
from django.utils import timezone

User = get_user_model()


class SupportTicket(models.Model):
    """Support ticket model for user inquiries and issues."""

    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]

    STATUS_CHOICES = [
        ('open', 'Open'),
        ('in_progress', 'In Progress'),
        ('pending', 'Pending User Response'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    ]

    CATEGORY_CHOICES = [
        ('technical', 'Technical Issue'),
        ('billing', 'Billing & Subscription'),
        ('feature', 'Feature Request'),
        ('bug', 'Bug Report'),
        ('account', 'Account Management'),
        ('integration', 'Integration Help'),
        ('other', 'Other'),
    ]

    # Ticket Information
    ticket_id = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        db_index=True
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='support_tickets'
    )
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='support_tickets',
        help_text="Optional store related to this ticket"
    )

    # Ticket Details
    subject = models.CharField(
        max_length=200,
        validators=[MinLengthValidator(10)]
    )
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default='technical'
    )
    priority = models.CharField(
        max_length=10,
        choices=PRIORITY_CHOICES,
        default='medium'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='open',
        db_index=True
    )

    # Description
    description = models.TextField(
        validators=[MinLengthValidator(50)],
        help_text="Detailed description of the issue or inquiry"
    )

    # Additional Information
    attachment = models.FileField(
        upload_to='support_attachments/%Y/%m/',
        blank=True,
        null=True,
        help_text="Screenshot or document attachment"
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    last_response_from = models.CharField(
        max_length=10,
        choices=[('user', 'User'), ('support', 'Support')],
        default='user'
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['ticket_id']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        return f"[{self.ticket_id}] {self.subject}"

    def save(self, *args, **kwargs):
        """Generate ticket ID on creation if not exists."""
        if not self.ticket_id:
            # Generate ticket ID like SUP-20240709-0001
            date_str = timezone.now().strftime('%Y%m%d')
            last_ticket = SupportTicket.objects.filter(
                ticket_id__contains=date_str
            ).order_by('-ticket_id').first()

            if last_ticket:
                # Extract sequence number and increment
                last_seq = int(last_ticket.ticket_id.split('-')[-1])
                new_seq = last_seq + 1
            else:
                new_seq = 1

            self.ticket_id = f"SUP-{date_str}-{new_seq:04d}"
        super().save(*args, **kwargs)

    @property
    def is_open(self):
        """Check if ticket is in an open state."""
        return self.status in ['open', 'in_progress', 'pending']

    @property
    def response_time_hours(self):
        """Calculate hours from creation to resolution."""
        if self.resolved_at:
            delta = self.resolved_at - self.created_at
            return delta.total_seconds() / 3600
        return None


class TicketComment(models.Model):
    """Comments and responses on support tickets."""

    ticket = models.ForeignKey(
        SupportTicket,
        on_delete=models.CASCADE,
        related_name='comments'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='ticket_comments'
    )
    is_staff_response = models.BooleanField(
        default=False,
        help_text="Whether this comment is from support staff"
    )
    content = models.TextField(
        validators=[MinLengthValidator(5)]
    )
    attachment = models.FileField(
        upload_to='support_comments/%Y/%m/',
        blank=True,
        null=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_internal = models.BooleanField(
        default=False,
        help_text="Internal note - not visible to user"
    )

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        prefix = "Staff" if self.is_staff_response else "User"
        return f"{prefix} comment on {self.ticket.ticket_id}"


class FAQCategory(models.Model):
    """FAQ Categories for organizing help articles."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    icon = models.CharField(
        max_length=50,
        default='bi-question-circle',
        help_text="Bootstrap icon class"
    )
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return self.name


class FAQArticle(models.Model):
    """Frequently Asked Questions articles."""

    category = models.ForeignKey(
        FAQCategory,
        on_delete=models.CASCADE,
        related_name='articles'
    )
    question = models.CharField(max_length=300)
    answer = models.TextField()
    slug = models.SlugField(max_length=300, unique=True)
    order = models.IntegerField(default=0)
    views = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'question']
        indexes = [
            models.Index(fields=['slug', 'is_active']),
        ]

    def __str__(self):
        return self.question

    def increment_view(self):
        """Increment view count."""
        self.views += 1
        self.save(update_fields=['views'])
