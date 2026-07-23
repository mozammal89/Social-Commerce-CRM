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


# ---------------------------------------------------------------------------
# OAuth 2.0 — authorization-code flow with PKCE
# ---------------------------------------------------------------------------
TIKTOK_OAUTH_BASE = "https://www.tiktok.com"
TIKTOK_OAUTH_AUTHORIZE_PATH = "/v2/auth/authorize/"

# Scopes required for OAuth. ``user.info.basic`` is the only scope
# available to every app out of the box — business messaging scopes
# (``business.msg.send`` etc.) require separate product approval and
# vary by app. The CRM calls the messaging API with server-to-server
# tokens, so we only need the user identity scope here.
DEFAULT_OAUTH_SCOPES = [
    "user.info.basic",
]


def generate_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code_verifier + code_challenge pair.

    TikTok requires PKCE (Proof Key for Code Exchange) for the OAuth
    authorization-code flow. The ``code_verifier`` is a random 43-128
    char string; the ``code_challenge`` is its SHA256 hash, base64url-
    encoded (the ``S256`` method).

    Returns ``(code_verifier, code_challenge)``.
    """
    import base64
    import hashlib
    import secrets

    # 32 random bytes → 43 base64url chars (the minimum safe length).
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def build_authorize_url(
    *,
    client_key: str,
    redirect_uri: str,
    state: str = "",
    scopes: list[str] | None = None,
    code_challenge: str = "",
) -> str:
    """Build the TikTok OAuth 2.0 authorization URL (with PKCE).

    The user clicks this URL in their browser, logs into TikTok, and
    approves the requested scopes. TikTok then redirects back to
    ``redirect_uri`` with ``?code=<auth_code>&state=<state>``.

    ``code_challenge`` is the PKCE challenge (SHA256 of the verifier).
    It's REQUIRED by TikTok — generate it via ``generate_pkce_pair()``
    and pass the matching ``code_verifier`` to
    ``exchange_authorization_code()``.

    ``redirect_uri`` must be registered in the TikTok developer console.
    """
    from urllib.parse import urlencode

    scope_list = scopes or DEFAULT_OAUTH_SCOPES
    params = {
        "client_key": client_key,
        "scope": ",".join(scope_list),
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state or "",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{TIKTOK_OAUTH_BASE}{TIKTOK_OAUTH_AUTHORIZE_PATH}?{urlencode(params)}"


def exchange_authorization_code(
    *,
    client_key: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    code_verifier: str = "",
) -> dict[str, Any]:
    """Exchange an OAuth authorization code for access + refresh tokens.

    Called from the OAuth callback handler after TikTok redirects back
    with ``?code=...``. The ``code_verifier`` must match the
    ``code_challenge`` sent in the authorize URL (PKCE).

    Returns::

        {
          "access_token": "...",        # ~24h validity
          "expires_in": 86400,
          "refresh_token": "...",       # ~30 days
          "refresh_expires_in": 2592000,
          "token_type": "Bearer",
          "open_id": "..."
        }

    Raises ``AuthenticationError`` on failure.
    """
    url = f"{TIKTOK_API_BASE}/v2/oauth/token/"
    data = {
        "client_key": client_key,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    if code_verifier:
        data["code_verifier"] = code_verifier
    try:
        resp = requests.post(url, data=data, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        raise AuthenticationError(f"TikTok token exchange request failed: {exc}") from exc
    return _handle_response(resp, action="token_exchange")


def get_business_info(*, account: "ConnectedAccount") -> dict[str, Any]:
    """Verify the access token by querying the user's basic info.

    TikTok doesn't expose a dedicated "verify token" endpoint. Instead,
    we call ``/v2/user/info/`` with the access token — if it returns
    successfully, the token is valid. Returns the user's profile info
    on success; raises ``AuthenticationError`` on any non-2xx response.
    """
    url = f"{TIKTOK_API_BASE}/v2/user/info/"
    fields = "open_id,union_id,display_name,avatar_url"
    params = {"fields": fields}
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
