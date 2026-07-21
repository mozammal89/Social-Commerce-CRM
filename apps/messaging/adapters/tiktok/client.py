"""
TikTok Business Messaging HTTP client.

TikTok's Business Messaging API is part of the TikTok Open Platform
(``open.tiktokapis.com``). Like Meta's Graph API it uses OAuth-issued
``access_token`` (Bearer) auth and scopes requests to a specific
business account via the ``business_id`` query/body parameter.

This client wraps the few endpoints the adapter needs:

* Send message:  POST /v2/business/msg/sendmessage
* Profile info:  POST /v2/business/msg/user/getinfo
* Token refresh: POST /v2/oauth/refresh_token/

References (TikTok for Developers — Business Messaging):
* https://developers.tiktok.com/doc/business-messaging-api
* https://developers.tiktok.com/doc/login-kit-web (OAuth 2.0 flow)

All requests time out at 20s to keep webhook ingestion responsive.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import requests

from ..exceptions import AuthenticationError, SendMessageError

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from ...models import ConnectedAccount

logger = logging.getLogger(__name__)

TIKTOK_API_BASE = "https://open.tiktokapis.com"
DEFAULT_TIMEOUT = 20  # seconds


def _creds(account: "ConnectedAccount") -> dict[str, Any]:
    """Return the (decrypted) credentials dict for an account.

    Defends against the encrypted-ciphertext / JSON-string / dict shapes
    the EncryptedJSONField may produce, same as the other adapters.
    """
    creds = account.credentials
    if isinstance(creds, dict):
        return creds
    if isinstance(creds, str):
        from ...fields import decrypt_value

        try:
            decrypted = decrypt_value(creds)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(
                "Failed to decrypt TikTok credentials for account %s: %s",
                account.id,
                exc,
            )
            return {}
        if isinstance(decrypted, dict):
            return decrypted
        if isinstance(decrypted, str):
            import ast
            import json

            try:
                parsed = json.loads(decrypted)
                return parsed if isinstance(parsed, dict) else {}
            except (json.JSONDecodeError, ValueError):
                try:
                    parsed = ast.literal_eval(decrypted)
                    return dict(parsed) if isinstance(parsed, dict) else {}
                except (ValueError, SyntaxError):
                    return {}
    return {}


def _headers(account: "ConnectedAccount") -> dict[str, str]:
    """Build the Bearer-auth headers for a TikTok API call."""
    token = _creds(account).get("access_token", "")
    if not token:
        raise SendMessageError(
            "Connected TikTok account has no access_token.",
            code="missing_token",
        )
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def send_message(
    *,
    account: "ConnectedAccount",
    payload: dict[str, Any],
) -> dict[str, Any]:
    """POST a send payload to the Business Messaging API.

    The caller (adapter) is responsible for building the
    ``{sender_user_id, recipient_user_id, message_type, content, ...}``
    body TikTok expects; this function adds auth + business_id and
    posts to ``/v2/business/msg/sendmessage``.
    """
    business_id = _creds(account).get("business_id") or account.external_id
    body = {"business_id": business_id, **payload}
    url = f"{TIKTOK_API_BASE}/v2/business/msg/sendmessage"
    try:
        resp = requests.post(url, headers=_headers(account), json=body, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        raise SendMessageError(
            f"TikTok send request failed: {exc}", code="transport_error"
        ) from exc
    return _handle_response(resp, action="send")


def get_user_info(
    *,
    account: "ConnectedAccount",
    user_id: str,
) -> dict[str, Any]:
    """Best-effort lookup of a TikTok user's public profile.

    Returns the user info block on success, ``{}`` on failure (profile
    enrichment must never break ingestion). The exact endpoint name has
    evolved across TikTok API versions; we try the documented v2 path
    and fall back gracefully if the merchant's app lacks the permission.
    """
    business_id = _creds(account).get("business_id") or account.external_id
    url = f"{TIKTOK_API_BASE}/v2/business/msg/user/getinfo"
    body = {"business_id": business_id, "user_id": user_id}
    try:
        resp = requests.post(url, headers=_headers(account), json=body, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning("TikTok user info request failed for user=%s: %s", user_id, exc)
        return {}
    if resp.status_code != 200:
        logger.info(
            "TikTok user info non-200 for user=%s: %s",
            user_id,
            resp.text[:200],
        )
        return {}
    try:
        data = resp.json()
    except ValueError:
        return {}
    # TikTok's data block lives under ``data.user`` on success.
    return (data.get("data") or {}).get("user") or data.get("data") or {}


def refresh_access_token(
    *,
    client_key: str,
    client_secret: str,
    refresh_token: str,
) -> dict[str, Any]:
    """Exchange a refresh token for a new TikTok access token.

    TikTok's refresh-token endpoint returns ``{access_token, expires_in,
    refresh_token, refresh_expires_in, token_type, open_id}``. Raises
    ``AuthenticationError`` on failure.
    """
    url = f"{TIKTOK_API_BASE}/v2/oauth/refresh_token/"
    params = {
        "client_key": client_key,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    try:
        resp = requests.post(url, params=params, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        raise AuthenticationError(f"TikTok token refresh request failed: {exc}") from exc
    return _handle_response(resp, action="refresh_token")


def get_business_info(*, account: "ConnectedAccount") -> dict[str, Any]:
    """Verify the access token + business id by querying the business.

    Returns the business's ``{business_id, name, ...}`` on success;
    raises ``AuthenticationError`` on any non-2xx response. Used as the
    canonical ``verify_credentials`` check.
    """
    business_id = _creds(account).get("business_id") or account.external_id
    url = f"{TIKTOK_API_BASE}/v2/business/get/"
    params = {"business_id": business_id}
    try:
        resp = requests.get(url, headers=_headers(account), params=params, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        raise AuthenticationError(f"TikTok verify request failed: {exc}") from exc
    return _handle_response(resp, action="verify")


def _handle_response(resp: requests.Response, *, action: str) -> dict[str, Any]:
    """Parse a TikTok Open API response, raising SendMessageError on failure.

    TikTok's error envelope is::

        {"data": {...},
         "error": {"code": "...", "message": "...", "log_id": "..."}}

    On success ``error.code == "ok"`` (or ``null``). On failure the
    ``code`` may be a string or an int depending on the endpoint.
    """
    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text}

    if resp.status_code >= 400:
        err = (data or {}).get("error", {}) if isinstance(data, dict) else {}
        code = str(err.get("code", resp.status_code))
        message = err.get("message", resp.text[:300])
        if action in ("refresh_token", "verify"):
            raise AuthenticationError(f"TikTok {action} failed: {message}")
        raise SendMessageError(f"TikTok {action} failed: {message}", code=code)

    # TikTok returns 200 with an ``error`` block when the request was
    # semantically invalid (bad permission, invalid recipient, etc.).
    if isinstance(data, dict):
        err = data.get("error") or {}
        err_code = err.get("code") if isinstance(err, dict) else None
        # ``ok`` / ``null`` / empty → success.
        if err_code and str(err_code).lower() not in ("ok", "0", "null", ""):
            message = err.get("message", "TikTok API error")
            if action in ("refresh_token", "verify"):
                raise AuthenticationError(f"TikTok {action} failed: {message}")
            raise SendMessageError(f"TikTok {action} failed: {message}", code=str(err_code))
    return data
