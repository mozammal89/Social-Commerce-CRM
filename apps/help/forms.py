"""
Forms for help and support functionality.
"""

from django import forms
from django.contrib.auth import get_user_model
from django.core.validators import MinLengthValidator
from django.utils import timezone

from .models import SupportTicket, FAQCategory, FAQArticle

User = get_user_model()


class SupportTicketForm(forms.ModelForm):
    """Form for submitting support tickets."""

    class Meta:
        model = SupportTicket
        fields = ['subject', 'category', 'priority', 'description', 'attachment', 'store']
        widgets = {
            'subject': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Brief summary of your issue',
                'required': True,
            }),
            'category': forms.Select(attrs={
                'class': 'form-select',
                'required': True,
            }),
            'priority': forms.Select(attrs={
                'class': 'form-select',
                'required': True,
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Please describe your issue in detail...',
                'rows': 6,
                'required': True,
            }),
            'attachment': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*,.pdf,.doc,.docx',
            }),
            'store': forms.Select(attrs={
                'class': 'form-select',
            }),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        # Filter stores for the user
        if user and 'store' in self.fields:
            from apps.stores.models import Store
            from apps.permissions.models import StoreMembership

            user_stores = Store.objects.filter(
                memberships__user=user,
                memberships__is_active=True,
                is_deleted=False
            )

            self.fields['store'].queryset = user_stores
            self.fields['store'].empty_label = "-- Select a store (optional) --"
            self.fields['store'].required = False

    def clean_subject(self):
        """Validate subject length."""
        subject = self.cleaned_data.get('subject')
        if len(subject) < 10:
            raise forms.ValidationError("Subject must be at least 10 characters long.")
        return subject

    def clean_description(self):
        """Validate description length."""
        description = self.cleaned_data.get('description')
        if len(description) < 50:
            raise forms.ValidationError("Description must be at least 50 characters long. Please provide more details about your issue.")
        return description

    def save(self, commit=True):
        """Save ticket with user."""
        ticket = super().save(commit=False)
        if self.user:
            ticket.user = self.user
        if commit:
            ticket.save()
        return ticket


class TicketCommentForm(forms.Form):
    """Form for adding comments to support tickets."""

    content = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'placeholder': 'Type your response here...',
            'rows': 4,
            'required': True,
        }),
        validators=[MinLengthValidator(5)],
        help_text="Enter your message or response"
    )

    attachment = forms.FileField(
        required=False,
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': 'image/*,.pdf,.doc,.docx',
        })
    )


class FAQSearchForm(forms.Form):
    """Form for searching FAQ articles."""

    q = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search for answers...',
            'autofocus': True,
        })
    )

    category = forms.ModelChoiceField(
        queryset=FAQCategory.objects.filter(is_active=True),
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-select',
        }),
        empty_label="All Categories"
    )
