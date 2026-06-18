"""
Public template-tag module for the role/permission UI.

Load with ``{% load rp_ui %}``.
"""

from django import template

from ..context_processors import (
    role_permission_breadcrumbs,
    role_permission_sidebar_extra,
)

register = template.Library()


@register.simple_tag(takes_context=True)
def rp_breadcrumbs(context):
    """Render the role/permission breadcrumb list as HTML.

    Returns an empty string when the current page is not part of the
    role/permission UI.
    """
    request = context.get("request")
    if request is None:
        return ""
    crumbs = role_permission_breadcrumbs(request).get("rp_breadcrumbs", [])
    if not crumbs:
        return ""

    parts = ['<nav aria-label="breadcrumb"><ol class="breadcrumb mb-4">']
    home_url = crumbs[0]["url"] if crumbs[0].get("url") else "#"
    parts.append(
        '<li class="breadcrumb-item"><a href="{}"><i class="bi bi-house"></i> Home</a></li>'.format(
            home_url
        )
    )
    for crumb in crumbs[1:]:
        if crumb.get("url"):
            parts.append(
                '<li class="breadcrumb-item"><a href="{}">{}</a></li>'.format(
                    crumb["url"], crumb["title"],
                )
            )
        else:
            parts.append(
                '<li class="breadcrumb-item active" aria-current="page">{}</li>'.format(
                    crumb["title"]
                )
            )
    parts.append("</ol></nav>")
    return "".join(parts)


@register.simple_tag(takes_context=True)
def rp_sidebar_active(context, url_name):
    """Return ``"active"`` if the current URL name matches."""
    request = context.get("request")
    match = getattr(request, "resolver_match", None) if request else None
    if not match:
        return ""
    if match.url_name == url_name and match.app_name == "role_permission":
        return "active"
    return ""
