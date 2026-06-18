"""
DRF exception handler that returns structured 403 responses for the RBAC
system, including the required permission / feature that was missing.

Wire it in via::

    REST_FRAMEWORK = {
        ...,
        "EXCEPTION_HANDLER": "apps.permissions.exception_handler.rbac_exception_handler",
    }
"""

from __future__ import annotations

from rest_framework.views import exception_handler


def rbac_exception_handler(exc, context):
    """
    Wrap DRF's default exception handler and enrich 403 responses with
    machine-readable fields so the frontend can show a useful message.
    """
    response = exception_handler(exc, context)
    if response is None:
        return None

    if response.status_code == 403:
        # DRF stores data as either a dict or a list — normalize to a dict.
        original = response.data
        if isinstance(original, dict):
            detail = original.get("detail") or original.get("message") or "Permission denied."
        else:
            detail = str(original)

        response.data = {
            "error": "forbidden",
            "detail": str(detail) if detail else "Permission denied.",
            "required_permission": getattr(exc, "required_permission", None),
            "required_feature": getattr(exc, "required_feature", None),
        }
    return response
