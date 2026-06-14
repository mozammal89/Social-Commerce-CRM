"""
URL configuration for Social Commerce CRM project.
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

# Template Views
from apps.core.views_template import home

urlpatterns = [
    path("", home, name="home"),  # Home page (template-based)
    path("admin/", admin.site.urls),
    path("dashboard/", include("apps.dashboard.urls")),
    path("auth/", include("apps.accounts.urls")),  # Template-based auth
    path("customers/", include("apps.customers.urls")),
    path("products/", include("apps.products.urls")),
    path("orders/", include("apps.orders.urls")),
    path("marketing/", include("apps.marketing.urls")),
    path("reports/", include("apps.reports.urls")),
    path("settings/", include("apps.settings.urls")),
    path("help/", include("apps.help.urls")),
    
    # API Routes
    path("api/v1/health/", include("apps.core.urls")),
    path("api/v1/auth/", include("apps.accounts.urls_api")),  # API routes
    path("api/v1/stores/", include("apps.stores.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    
    # Convenience redirects for common auth routes
    path("login/", RedirectView.as_view(url='/auth/login/', permanent=False), name='login_redirect'),
    path("register/", RedirectView.as_view(url='/auth/register/', permanent=False), name='register_redirect'),
    path("logout/", RedirectView.as_view(url='/auth/logout/', permanent=False), name='logout_redirect'),
    path("password-reset/", RedirectView.as_view(url='/auth/password-reset/', permanent=False), name='password_reset_redirect'),
    
    # Account routes redirect
    path("accounts/profile/", RedirectView.as_view(url='/auth/profile/', permanent=False), name='accounts_profile_redirect'),
    path("accounts/", RedirectView.as_view(url='/auth/', permanent=False), name='accounts_redirect'),
]

if settings.DEBUG:
    from django.conf.urls.static import static
    from django.views.generic import TemplateView

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += [path("", TemplateView.as_view(template_name="index.html"))]

admin.site.site_header = "Social Commerce CRM Admin"
admin.site.site_title = "Social Commerce CRM Admin Portal"
admin.site.index_title = "Welcome to Social Commerce CRM Portal"
