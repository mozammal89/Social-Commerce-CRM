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

import ast
import json
import logging
from typing import TYPE_CHECKING, Any

import requests

from ..exceptions import AuthenticationError, SendMessageError
from ...fields import decrypt_value

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from ...models import ConnectedAccount

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v18.0"
DEFAULT_TIMEOUT = 20  # seconds


def _page_token(account: "ConnectedAccount") -> str:
    """Read the page access token from the (decrypted) credentials."""
    creds = account.credentials or {}

    # If credentials is a string, it might be encrypted or a JSON string
    if isinstance(creds, str):
        try:
            decrypted = decrypt_value(creds)
            if isinstance(decrypted, dict):
                creds = decrypted
            elif isinstance(decrypted, str):
                try:
                    creds = json.loads(decrypted)
                except (json.JSONDecodeError, ValueError):
                    try:
                        creds = ast.literal_eval(decrypted)
                        if not isinstance(creds, dict):
                            logger.warning(
                                "Parsed credentials is not a dict for account %s", account.id
                            )
                            creds = {}
                    except (ValueError, SyntaxError):
                        logger.warning(
                            "Could not parse credentials as JSON or Python dict for account %s",
                            account.id,
                        )
                        creds = {}
        except Exception as e:
            logger.error("Failed to decrypt/parse credentials for account %s: %s", account.id, e)
            creds = {}

    token = creds.get("page_access_token", "") if isinstance(creds, dict) else ""
    if not token:
        raise SendMessageError(
            "Connected Facebook account has no page_access_token.", code="missing_token"
        )
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
    logger.debug(
        "Facebook send request: url=%s, recipient=%s, payload=%s", url, recipient_psid, payload
    )
    print("Facebook send request: url=%s, recipient=%s, payload=%s", url, recipient_psid, payload)
    try:
        resp = requests.post(url, params=params, json=payload, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        raise SendMessageError(
            f"Facebook send request failed: {exc}", code="transport_error"
        ) from exc

    logger.debug("Facebook send response: status=%s, body=%s", resp.status_code, resp.text[:500])
    print("Facebook send response: status=%s, body=%s", resp.status_code, resp.text[:500])
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


def exchange_long_lived_token(
    *, app_id: str, app_secret: str, short_lived_token: str
) -> dict[str, Any]:
    """Exchange a short-lived user token for a long-lived user token.

    Returns Graph API's ``{access_token, token_type, expires_in}`` where
    ``expires_in`` is seconds until expiry (~60 days). Raises
    ``AuthenticationError`` on failure.

    See: https://developers.facebook.com/docs/facebook-login/guides/advanced/manual-flow
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


def fetch_page_tokens(*, user_access_token: str) -> list[dict[str, Any]]:
    """Retrieve long-lived Page access tokens via ``GET /me/accounts``.

    Given a **long-lived user access token**, this returns one entry per
    Facebook Page the user manages, each carrying a long-lived page token
    that does **not** expire while the user token remains valid.

    Returns ``[{id, name, access_token, ...}, ...]`` (empty list if the
    user manages no pages). Raises ``AuthenticationError`` on failure.
    """
    url = f"{GRAPH_API_BASE}/me/accounts"
    params = {
        "fields": "id,name,access_token",
        "access_token": user_access_token,
    }
    try:
        resp = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        raise AuthenticationError(f"Facebook /me/accounts request failed: {exc}") from exc

    data = _handle_response(resp, action="token_exchange")
    return data.get("data", [])


def debug_token(*, input_token: str, app_id: str, app_secret: str) -> dict[str, Any]:
    """Inspect a token's validity and expiry via ``GET /debug_token``.

    Returns the Graph ``data`` object, e.g.::

        {"data": {"is_valid": True, "type": "USER|PAGE",
                  "expires_at": 1234567890, "app_id": "...", ...}}

    ``expires_at`` is a Unix timestamp (``0`` means never expires — true
    for page tokens derived from a long-lived user token). Raises
    ``AuthenticationError`` on failure.
    """
    # The debug_token endpoint requires an app access token.
    app_access_token = f"{app_id}|{app_secret}"
    url = f"{GRAPH_API_BASE}/debug_token"
    params = {
        "input_token": input_token,
        "access_token": app_access_token,
    }
    try:
        resp = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        raise AuthenticationError(f"Facebook debug_token request failed: {exc}") from exc

    data = _handle_response(resp, action="verify")
    return data


def verify_token(*, account: "ConnectedAccount") -> dict[str, Any]:
    """Verify the page access token by calling ``GET /me``.

    The canonical "is this token valid?" check. Returns the page's
    ``{id, name}`` on success; raises ``AuthenticationError`` on any
    non-2xx response (invalid/expired token, wrong permissions, ...).
    """
    url = f"{GRAPH_API_BASE}/me"
    params = {"fields": "id,name", "access_token": _page_token(account)}
    try:
        resp = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
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
