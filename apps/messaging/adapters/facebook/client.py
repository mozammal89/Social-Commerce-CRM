"""
Facebook Messenger (Graph API) HTTP client.

A thin wrapper around the few Graph API endpoints the adapter needs:
send messages, fetch sender profiles, and exchange short-lived tokens
for long-lived page access tokens. Keeping HTTP in one place lets the
adapter methods stay focused on payload mapping.

References (Graph API v18.0+):
* Send API:        POST /{page-id}/messages
* Profile API:     GET  /{sender-psid}?fields=first_name,last_name,profile_pic
* Long-lived token: https://developers.facebook.com/docs/facebook-login/guides/advanced/manual-flow

All requests are made with the ``requests`` library and time out at 20s
to keep webhook ingestion responsive.
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


def _page_token(account: "ConnectedAccount") -> str:
    """Read the page access token from the (decrypted) credentials."""
    token = (account.credentials or {}).get("page_access_token", "")
    if not token:
        raise SendMessageError("Connected Facebook account has no page_access_token.", code="missing_token")
    return token


def send(
    *,
    account: "ConnectedAccount",
    recipient_psid: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """POST to the Send API and return the parsed JSON response.

    ``payload`` is the ``messaging`` body (recipient + message). Raises
    ``SendMessageError`` on non-2xx responses or transport failure.
    """
    url = f"{GRAPH_API_BASE}/{account.external_id}/messages"
    params = {"access_token": _page_token(account)}
    try:
        resp = requests.post(url, params=params, json=payload, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        raise SendMessageError(f"Facebook send request failed: {exc}", code="transport_error") from exc

    return _handle_response(resp, action="send")


def fetch_profile(
    *,
    account: "ConnectedAccount",
    psid: str,
) -> dict[str, Any]:
    """GET the sender's public profile (name + avatar).

    Returns ``{first_name, last_name, profile_pic}`` or an empty dict on
    failure (profile fetch is best-effort and must not block ingestion).
    """
    url = f"{GRAPH_API_BASE}/{psid}"
    params = {
        "fields": "first_name,last_name,profile_pic",
        "access_token": _page_token(account),
    }
    try:
        resp = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning("Facebook profile fetch failed for psid=%s: %s", psid, exc)
        return {}

    if resp.status_code != 200:
        logger.warning("Facebook profile fetch non-200 for psid=%s: %s", psid, resp.text[:200])
        return {}
    return resp.json()


def exchange_long_lived_token(*, app_id: str, app_secret: str, short_lived_token: str) -> dict[str, Any]:
    """Exchange a short-lived user token for a long-lived user token.

    Returns Graph API's ``{access_token, token_type, expires_in}``.
    Raises ``AuthenticationError`` on failure.
    """
    url = f"{GRAPH_API_BASE}/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": short_lived_token,
    }
    try:
        resp = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        raise AuthenticationError(f"Facebook token exchange request failed: {exc}") from exc

    data = _handle_response(resp, action="token_exchange")
    return data


def verify_token(*, account: "ConnectedAccount") -> dict[str, Any]:
    """Verify the page access token by calling ``GET /me``.

    The canonical "is this token valid?" check. Returns the page's
    ``{id, name}`` on success; raises ``AuthenticationError`` on any
    non-2xx response (invalid/expired token, wrong permissions, ...).
    """
    url = f"{GRAPH_API_BASE}/me"
    params = {"fields": "id,name", "access_token": _page_token(account)}
    print('-------------- facegook params --------------', params)
    try:
        resp = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
        print('-------------- facegook verify resp --------------', resp.text)
    except requests.RequestException as exc:
        print('-------------- facegook error --------------', exc)
        raise AuthenticationError(f"Facebook verify request failed: {exc}") from exc
    return _handle_response(resp, action="verify")


def _handle_response(resp: requests.Response, *, action: str) -> dict[str, Any]:
    """Parse a Graph API response, raising SendMessageError on failure."""
    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text}

    if resp.status_code >= 400:
        # Graph error shape: {"error": {"message", "type", "code", "fbtrace_id"}}
        err = (data or {}).get("error", {}) if isinstance(data, dict) else {}
        code = str(err.get("code", resp.status_code))
        message = err.get("message", resp.text[:300])
        if action in ("token_exchange", "verify"):
            raise AuthenticationError(f"Facebook {action} failed: {message}")
        raise SendMessageError(f"Facebook {action} failed: {message}", code=code)
    return data
