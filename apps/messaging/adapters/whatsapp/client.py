"""
WhatsApp Business Cloud API HTTP client.

Wraps the Cloud API endpoints the adapter needs: send messages and
optionally look up a contact's WhatsApp display name. The Cloud API is
token-authenticated (a system-user access token) and scoped to a
specific phone number ID.

References (Cloud API v18.0):
* Send:    POST https://graph.facebook.com/v18.0/{phone_number_id}/messages
* Contacts: POST https://graph.facebook.com/v18.0/{phone_number_id}/contacts

All requests time out at 20s.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import requests

from ..exceptions import AuthenticationError, SendMessageError

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from ...models import ConnectedAccount

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v18.0"
DEFAULT_TIMEOUT = 20  # seconds


def _headers(account: "ConnectedAccount") -> dict[str, str]:
    token = (account.credentials or {}).get("access_token", "")
    if not token:
        raise SendMessageError("Connected WhatsApp account has no access_token.", code="missing_token")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def send(
    *,
    account: "ConnectedAccount",
    payload: dict[str, Any],
) -> dict[str, Any]:
    """POST a send payload to the Cloud API and return parsed JSON."""
    url = f"{GRAPH_API_BASE}/{account.external_id}/messages"
    try:
        resp = requests.post(url, headers=_headers(account), json=payload, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        raise SendMessageError(f"WhatsApp send request failed: {exc}", code="transport_error") from exc
    return _handle_response(resp, action="send")


def fetch_contacts(
    *,
    account: "ConnectedAccount",
    phones: list[str],
) -> dict[str, Any]:
    """Best-effort lookup of WhatsApp status/name for phone numbers.

    Returns the ``contacts`` block from the response or ``{}`` on failure.
    Profile enrichment is never fatal to ingestion.
    """
    if not phones:
        return {}
    url = f"{GRAPH_API_BASE}/{account.external_id}/contacts"
    payload = {"blocking": "wait", "contacts": phones}
    try:
        resp = requests.post(url, headers=_headers(account), json=payload, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning("WhatsApp contacts lookup failed: %s", exc)
        return {}
    if resp.status_code != 200:
        logger.warning("WhatsApp contacts lookup non-200: %s", resp.text[:200])
        return {}
    return resp.json()


def _handle_response(resp: requests.Response, *, action: str) -> dict[str, Any]:
    """Parse a Cloud API response, raising SendMessageError on failure."""
    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text}

    if resp.status_code >= 400:
        err = (data or {}).get("error", {}) if isinstance(data, dict) else {}
        code = str(err.get("code", resp.status_code))
        message = err.get("message", resp.text[:300])
        if action == "authenticate":
            raise AuthenticationError(f"WhatsApp authentication failed: {message}")
        raise SendMessageError(f"WhatsApp {action} failed: {message}", code=code)
    return data
