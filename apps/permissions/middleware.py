"""
RBAC middleware.

Two middlewares live here:

1. ``AuditContextMiddleware`` — populates a request-scoped context var
   that ``apps.permissions.signals`` reads when writing ``AuditLog`` rows.
   This is how we capture actor/IP/user-agent/request-id without passing
   them through every save call.

2. ``HTMX403Middleware`` — converts a 403 response into a partial
   fragment for HTMX requests, so a sidebar that hides after a
   permission denial returns a clean inline replacement instead of
   the full error page.
"""

from __future__ import annotations

import contextvars
import uuid
from typing import Optional

from django.http import HttpResponse
from django.template.loader import render_to_string


# ---------------------------------------------------------------------------
# Audit request context — contextvars so it survives across thread boundaries
# (Celery tasks can populate it too if needed).
# ---------------------------------------------------------------------------
_req_ctx: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "rbac_req_ctx", default=None
)


def current_request_context() -> Optional[dict]:
    """Return the dict stored by ``AuditContextMiddleware``, or None."""
    return _req_ctx.get()


def set_request_context(**kwargs) -> None:
    """
    Manual setter — useful for management commands, Celery tasks, or tests.
    """
    ctx = _req_ctx.get() or {}
    ctx.update({k: v for k, v in kwargs.items() if v is not None or k in ctx})
    _req_ctx.set(ctx)


class AuditContextMiddleware:
    """
    Populate the audit context for every request. Should sit AFTER
    AuthenticationMiddleware and CurrentStoreMiddleware (if present).

    The context is reset at the end of the request so subsequent requests
    don't inherit state.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        store = getattr(request, "store", None)
        ctx = {
            "user": getattr(request, "user", None),
            "store_id": getattr(store, "id", None) if store else None,
            "ip": request.META.get("REMOTE_ADDR"),
            "ua": (request.META.get("HTTP_USER_AGENT") or "")[:512],
            "request_id": (
                request.META.get("HTTP_X_REQUEST_ID") or uuid.uuid4().hex
            ),
        }
        token = _req_ctx.set(ctx)
        try:
            response = self.get_response(request)
        finally:
            _req_ctx.reset(token)
        # Expose request_id on the response for traceability.
        response["X-Request-ID"] = ctx["request_id"]
        return response


class HTMX403Middleware:
    """
    For HTMX requests that produce a 403, return the partial template
    ``errors/_403_partial.html`` instead of the full error page.

    This keeps the surrounding page alive: the sidebar/topnav can swap
    in a small "access denied" notice without navigating away.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_response(self, request, response):
        if response.status_code == 403 and request.headers.get("HX-Request"):
            try:
                body = render_to_string(
                    "errors/_403_partial.html",
                    request=request,
                )
            except Exception:
                # Fall back to plain text if the template doesn't exist yet.
                body = "Access denied."
            response = HttpResponse(body, status=403)
        return response