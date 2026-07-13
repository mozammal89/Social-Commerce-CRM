"""
Secure webhook endpoints for all messaging channels.

A single **generic dispatcher** serves every channel: the URL carries
the ``channel_slug`` and ``account_id``, and the corresponding adapter
knows how to verify and parse that channel's payload. Adding a new
channel needs no new view or URL — just a new adapter + a registered
channel slug. This is the Open/Closed payoff from Phase 2.

Security model
--------------
Webhooks are **not** authenticated by Django session/JWT. They come
from external platforms, so authentication is delegated to the adapter:

* **GET** — the subscription handshake (Facebook/WhatsApp ``hub.mode=
  subscribe``). The adapter checks ``hub.verify_token`` against the
  account's token and returns the ``hub.challenge`` to echo.
* **POST** — event delivery. The adapter verifies the cryptographic
  signature (Facebook ``X-Hub-Signature-256``, WhatsApp
  ``X-Hub-Signature-256``) using the account's app secret. If
  verification fails we return ``403`` and persist nothing.

Performance model
-----------------
Platforms require a ``200 OK`` within ~5 seconds and will redeliver
(and eventually throttle) otherwise. The POST handler therefore does
the **minimum synchronous work** — load the account, verify the
signature — then hands the raw body to the
``process_webhook_payload`` Celery task for async parsing + ingestion.
If Celery is unavailable (dev), the task runs eagerly (synchronously)
so the flow still works end-to-end.

Account lookup is by ``account_id`` (UUID) and is inherently store-
isolated: a connected account belongs to exactly one store, so a
webhook can only ever touch that store's data.
"""

from __future__ import annotations

import json
import logging

from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .adapters import WebhookVerificationError, get_adapter_for_account
from .adapters.exceptions import AdapterError
from .models import ConnectedAccount
from .tasks import process_webhook_payload

# Ensure Celery app is initialized for task queuing
from config import celery  # noqa: F401

logger = logging.getLogger(__name__)

# Methods both supported platforms use. ``require_http_methods`` +
# csrf_exempt is the established pattern for callback endpoints.
_ALLOWED_METHODS = ["GET", "POST"]


@csrf_exempt
@require_http_methods(_ALLOWED_METHODS)
def channel_webhook(
    request: HttpRequest,
    channel_slug: str,
    account_id: str,
) -> HttpResponse:
    """Generic webhook dispatcher for all messaging channels.

    URL: ``/api/v1/messaging/webhooks/<slug:channel_slug>/<uuid:account_id>/``

    * ``GET``  → subscription verification (echo ``hub.challenge``).
    * ``POST`` → verify signature, then queue async processing; return 200.
    """
    # Resolve the connected account. A bad/unknown account_id must never
    # reveal whether the account exists, so all lookup failures return 404.
    account = (
        ConnectedAccount.objects
        .select_related("store", "channel")
        .filter(pk=account_id, channel__slug=channel_slug)
        .first()
    )
    if account is None:
        logger.warning(
            "Webhook for unknown account=%s channel=%s", account_id, channel_slug,
        )
        return HttpResponse(status=404)

    adapter = get_adapter_for_account(account)

    if request.method == "GET":
        return _handle_verification(request, account, adapter)
    return _handle_event(request, account, adapter)


# ---------------------------------------------------------------------------
# GET — subscription verification
# ---------------------------------------------------------------------------
def _handle_verification(request, account, adapter) -> HttpResponse:
    """Verify the ``hub.verify_token`` handshake and echo the challenge."""
    query_params = {k: v for k, v in request.GET.items()}
    try:
        ok, challenge = adapter.verify_webhook(
            method="GET",
            headers=_header_dict(request),
            query_params=query_params,
            body=b"",
            account=account,
        )
    except WebhookVerificationError as exc:
        logger.warning("Webhook verification failed (account=%s): %s", account.id, exc)
        return HttpResponse(status=403)
    except AdapterError as exc:
        logger.warning("Webhook verification adapter error (account=%s): %s", account.id, exc)
        return HttpResponse(status=400)

    if not ok:
        return HttpResponse(status=403)

    # ``challenge`` is the string to echo for FB/WA subscription.
    return HttpResponse(challenge or "", content_type="text/plain", status=200)


# ---------------------------------------------------------------------------
# POST — event delivery
# ---------------------------------------------------------------------------
def _handle_event(request, account, adapter) -> HttpResponse:
    """Verify the signature, then hand the body to the async processor."""
    body = request.body
    if not body:
        # Empty body is almost always a misconfigured webhook; ack 200 so
        # the platform doesn't hammer us with retries, but log it.
        logger.info("Empty webhook body for account=%s", account.id)
        return HttpResponse(status=200)

    try:
        ok, _ = adapter.verify_webhook(
            method="POST",
            headers=_header_dict(request),
            query_params={k: v for k, v in request.GET.items()},
            body=body,
            account=account,
        )
    except WebhookVerificationError as exc:
        # Signature mismatch → refuse and log. Return 403 so the platform
        # (and we) can tell genuine events from spoofing attempts.
        logger.warning("Webhook signature verification failed (account=%s): %s", account.id, exc)
        return HttpResponse(status=403)
    except AdapterError as exc:
        logger.warning("Webhook verification adapter error (account=%s): %s", account.id, exc)
        return HttpResponse(status=400)

    if not ok:
        return HttpResponse(status=403)

    # Hand off to Celery for parsing + ingestion. Pass the body as text
    # (Celery JSON-serializes args); the task re-encodes for the adapter.
    try:
        body_text = body.decode("utf-8")
        # Sanity: it should be valid JSON for our adapters. If not, the
        # task's parse step will fail gracefully and retry.
        json.loads(body_text)
    except (UnicodeDecodeError, json.JSONDecodeError):
        logger.warning("Non-JSON/undecodable webhook body for account=%s", account.id)
        # Still ack 200 to avoid retry storms; the payload is unusable.
        return HttpResponse(status=200)

    process_webhook_payload.delay(
        account_id=str(account.id),
        headers=_header_dict(request),
        body=body_text,
    )
    # Fast 200 so the platform considers delivery successful.
    return HttpResponse(status=200)


def _header_dict(request: HttpRequest) -> dict[str, str]:
    """Extract a plain dict of headers (case-insensitive lookups happen in adapters)."""
    return {k: v for k, v in request.headers.items()}
