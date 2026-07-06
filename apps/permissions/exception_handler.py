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

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from .exceptions import DowngradeOverCapacity, PlanLimitExceeded


def rbac_exception_handler(exc, context):
    """
    Wrap DRF's default exception handler and enrich 403 responses with
    machine-readable fields so the frontend can show a useful message.

    Also converts RBAC-specific exceptions (e.g. ``PlanLimitExceeded``)
    into structured 403 responses so the frontend gets a clean error
    payload instead of a 500.
    """
    # Plan limit hit: convert to a 403 with a structured payload so the
    # front-end can show "upgrade your plan" UI.
    if isinstance(exc, PlanLimitExceeded):
        return Response(
            {
                "error": "plan_limit_exceeded",
                "detail": (
                    f"You've reached your plan's {exc.limit_attr} limit "
                    f"({exc.current}/{exc.cap}). Upgrade your plan to continue."
                ),
                "limit_attr": exc.limit_attr,
                "current": exc.current,
                "cap": exc.cap,
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    # Downgrade would leave the user over the new plan's caps.
    # Return a 400 with the structured impact so the frontend can
    # show the user exactly which rows to delete / soft-deactivate
    # before retrying. 400 (not 403) because the request is
    # well-formed but the *requested transition* is not allowed
    # given current state.
    if isinstance(exc, DowngradeOverCapacity):
        return Response(
            {
                "error": "downgrade_over_capacity",
                "detail": str(exc),
                "new_plan_slug": exc.new_plan_slug,
                "limits": exc.limits,
                "stores": exc.stores,
                "users": exc.users,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

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
