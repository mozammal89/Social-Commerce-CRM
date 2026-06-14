"""
Template-based views for Social Commerce CRM.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.contrib.auth.views import (
    LoginView as DjangoLoginView,
    LogoutView as DjangoLogoutView,
    PasswordResetView as DjangoPasswordResetView,
    PasswordResetConfirmView as DjangoPasswordResetConfirmView,
    PasswordResetDoneView as DjangoPasswordResetDoneView,
    PasswordResetCompleteView as DjangoPasswordResetCompleteView,
    PasswordChangeView as DjangoPasswordChangeView,
)
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.urls import reverse_lazy
from django.http import HttpResponse

from apps.accounts.forms import (
    CustomPasswordResetForm,
    LoginForm,
    RegistrationForm,
    ProfileForm,
    CustomPasswordChangeForm,
)
from apps.stores.models import Store


User = get_user_model()


class LoginView(DjangoLoginView):
    """Custom login view with template rendering."""
    template_name = 'auth/login.html'
    form_class = LoginForm
    redirect_authenticated_user = True


class LogoutView(DjangoLogoutView):
    """Custom logout view with template rendering."""
    template_name = 'auth/login.html'
    
    def get(self, request, *args, **kwargs):
        logout(request)
        messages.success(request, 'You have been logged out successfully.')
        return redirect('accounts:login')


class RegistrationView(DjangoPasswordResetDoneView):
    """Custom registration view."""
    template_name = 'auth/register.html'
    
    def get(self, request, *args, **kwargs):
        from apps.accounts.forms import RegistrationForm
        form = RegistrationForm()
        return render(request, self.template_name, {'form': form})
    
    def post(self, request, *args, **kwargs):
        from apps.accounts.forms import RegistrationForm
        form = RegistrationForm(request.POST, request.FILES)
        
        if form.is_valid():
            user = form.save()
            messages.success(
                request, 
                'Your account has been created successfully. You can now log in.'
            )
            return redirect('accounts:login')
        
        return render(request, self.template_name, {'form': form})


@login_required
def profile(request):
    """User profile view."""
    user_form = ProfileForm(instance=request.user)
    
    if request.method == 'POST':
        user_form = ProfileForm(request.POST, request.FILES, instance=request.user)
        
        if user_form.is_valid():
            user_form.save()
            messages.success(request, 'Your profile has been updated successfully.')
            return redirect('accounts:profile')
        else:
            messages.error(request, 'Please correct the errors below.')
    
    return render(request, 'accounts/profile.html', {
        'user_form': user_form,
    })


@login_required
def change_password(request):
    """Change password view."""
    if request.method == 'POST':
        form = CustomPasswordChangeForm(request.user, request.POST)
        
        if form.is_valid():
            form.save()
            messages.success(request, 'Your password has been changed successfully.')
            return redirect('accounts:change_password')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = CustomPasswordChangeForm(request.user)
    
    return render(request, 'accounts/change_password.html', {
        'form': form,
    })


@login_required
def avatar_upload(request):
    """Handle avatar upload."""
    if request.method == 'POST':
        user_form = ProfileForm(request.POST, request.FILES, instance=request.user)
        
        if user_form.is_valid():
            user_form.save()
            messages.success(request, 'Your profile picture has been updated successfully.')
            return redirect('accounts:profile')
        else:
            messages.error(request, 'Please correct the errors below.')
    
    return redirect('accounts:profile')


class CustomPasswordResetView(DjangoPasswordResetView):
    """Custom password reset view."""
    template_name = 'auth/password_reset.html'
    form_class = CustomPasswordResetForm
    success_url = reverse_lazy('accounts:password_reset_done')
    email_template_name = 'auth/password_reset_email.html'
    subject_template_name = 'auth/password_reset_subject.txt'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Override the default password_reset_confirm URL to use namespaced version
        context['protocol'] = 'https' if self.request.is_secure() else 'http'
        context['domain'] = self.request.get_host()
        return context


class CustomPasswordResetConfirmView(DjangoPasswordResetConfirmView):
    """Custom password reset confirm view."""
    template_name = 'auth/password_reset_confirm.html'
    success_url = reverse_lazy('accounts:password_reset_complete')


class CustomPasswordResetDoneView(DjangoPasswordResetDoneView):
    """Custom password reset done view."""
    template_name = 'auth/password_reset_done.html'


class CustomPasswordResetCompleteView(DjangoPasswordResetCompleteView):
    """Custom password reset complete view."""
    template_name = 'auth/password_reset_complete.html'


class CustomPasswordChangeView(DjangoPasswordChangeView):
    """Custom password change view."""
    template_name = 'accounts/change_password.html'
    form_class = CustomPasswordChangeForm
    success_url = reverse_lazy('accounts:change_password_done')
    
    def form_valid(self, form):
        messages.success(
            self.request,
            'Your password has been changed successfully.'
        )
        return super().form_valid(form)


@login_required
def change_password_done(request):
    """Password change done view."""
    return render(request, 'accounts/change_password_done.html')