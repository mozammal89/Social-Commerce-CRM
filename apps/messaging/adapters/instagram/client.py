"""
Instagram Direct (Messenger Platform) HTTP client.

Instagram messaging is delivered through Meta's Messenger Platform on the
Graph API. The endpoints mirror the Facebook Send/Profile APIs almost
exactly, with two differences that matter to us:

* The Send-API node is the **Instagram account id** (``ig-user-id``)
  rather than a Facebook Page id. DMs are sent via
  ``POST /{ig-user-id}/messages``.
* The sender profile endpoint exposes Instagram-specific fields
  (``username``, ``name``, ``profile_pic``, ``followers_count``,
  ``media_count``). It is queried by the customer's IGSID
  (Instagram-scoped id), not by a PSID.

Token lifecycle is identical to Facebook (same Meta OAuth, same
``/oauth/access_token`` long-lived exchange, same ``/me/accounts`` to
fetch the IG-connected page tokens). Those helpers live here too so the
Instagram adapter is fully self-contained.

References (Graph API v18.0+):
* Instagram Messaging Send API:
  POST /{ig-user-id}/messages
* Instagram sender profile:
  GET  /{igsid}?fields=name,username,profile_pic,followers_count
* Long-lived token exchange:
  GET  /oauth/access_token?grant_type=fb_exchange_token
* IG-connected Page tokens:
  GET  /me/accounts?fields=id,name,access_token,instagram_business_account

All requests time out at 20s to keep webhook ingestion responsive.
"""

from __future__ import annotations

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


def _creds_dict(account: "ConnectedAccount") -> dict[str, Any]:
    """Return the (decrypted) credentials dict for an account.

    The ``credentials`` field is an ``EncryptedJSONField``; depending on
    how the row was written it may already be a dict (decrypted
    transparently), a Fernet ciphertext string, or a JSON string. We
    handle all three shapes so the adapter never crashes on a legacy
    row.
    """
    creds = account.credentials
    if isinstance(creds, dict):
        return creds
    if isinstance(creds, str):
        try:
            decrypted = decrypt_value(creds)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(
                "Failed to decrypt Instagram credentials for account %s: %s", account.id, exc
            )
            return {}
        if isinstance(decrypted, dict):
            return decrypted
        if isinstance(decrypted, str):
            # Could be JSON or a Python dict-literal; try both.
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


def _ig_token(account: "ConnectedAccount") -> str:
    """Read the IG Page access token from the (decrypted) credentials."""
    token = _creds_dict(account).get("page_access_token", "")
    if not token:
        raise SendMessageError(
            "Connected Instagram account has no page_access_token.",
            code="missing_token",
        )
    return token


def send(
    *,
    account: "ConnectedAccount",
    recipient_igsid: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """POST to the IG Send API and return the parsed JSON response.

    ``payload`` is the ``message`` body (recipient + message). Raises
    ``SendMessageError`` on non-2xx responses or transport failure.
    """
    # The IG account id lives on ConnectedAccount.external_id.
    url = f"{GRAPH_API_BASE}/{account.external_id}/messages"
    params = {"access_token": _ig_token(account)}
    logger.debug(
        "Instagram send request: url=%s, recipient=%s, payload=%s",
        url,
        recipient_igsid,
        payload,
    )
    try:
        resp = requests.post(url, params=params, json=payload, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        raise SendMessageError(
            f"Instagram send request failed: {exc}", code="transport_error"
        ) from exc

    logger.debug(
        "Instagram send response: status=%s, body=%s",
        resp.status_code,
        resp.text[:500],
    )
    return _handle_response(resp, action="send")


def fetch_profile(
    *,
    account: "ConnectedAccount",
    igsid: str,
) -> dict[str, Any]:
    """GET the sender's Instagram profile (best-effort, multi-tier).

    Instagram Messaging exposes only two profile fields for a sender
    via ``GET /{igsid}?fields=...`` (the IGSID node, NOT the
    ``/{ig-user-id}`` Business Account node):

      * ``name``        — the sender's IG display name
      * ``profile_pic`` — public profile picture URL

    Other fields (``username``, ``followers_count``, ``media_count``)
    exist only on the IG Business Account node and are NOT available
    for messaging senders — requesting them raises Graph API error
    code 12 (``cannot_access_user_username_field``). Never raises —
    profile enrichment is best-effort.
    """
    return (
        _fetch_profile_fields(account, igsid, "name,profile_pic")
        or _fetch_profile_fields(account, igsid, "profile_pic")
        or {}
    )


def _fetch_profile_fields(
    account: "ConnectedAccount", igsid: str, fields: str
) -> dict[str, Any] | None:
    """One attempt to fetch ``fields`` for ``igsid``.

    Returns ``None`` on failure so the caller can fall back; returns the
    parsed dict on success (which may be empty).
    """
    url = f"{GRAPH_API_BASE}/{igsid}"
    params = {"fields": fields, "access_token": _ig_token(account)}
    try:
        resp = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning("Instagram profile fetch failed for igsid=%s: %s", igsid, exc)
        return None

    if resp.status_code != 200:
        logger.info(
            "Instagram profile fetch (fields=%s) non-200 for igsid=%s: %s",
            fields,
            igsid,
            resp.text[:200],
        )
        return None
    return resp.json()


def exchange_long_lived_token(
    *, app_id: str, app_secret: str, short_lived_token: str
) -> dict[str, Any]:
    """Exchange a short-lived user token for a long-lived one.

    Instagram uses the exact same Meta OAuth flow as Facebook. The
    returned token grants ~60 days of validity; the periodic refresh
    task re-fetches IG page tokens from it before expiry.
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
        raise AuthenticationError(f"Instagram token exchange request failed: {exc}") from exc

    return _handle_response(resp, action="token_exchange")


def fetch_page_tokens(*, user_access_token: str) -> list[dict[str, Any]]:
    """Retrieve IG-connected Page access tokens via ``GET /me/accounts``.

    Given a **long-lived user access token**, this returns one entry per
    Facebook Page the user manages. Instagram messaging requires the IG
    Professional account to be linked to a Page, so we eagerly request
    the linked ``instagram_business_account`` block — the adapter then
    matches on its ``id`` (= ``external_id`` on the account).

    Returns ``[{id, name, access_token, instagram_business_account: {id, username}}, ...]``.
    """
    url = f"{GRAPH_API_BASE}/me/accounts"
    params = {
        "fields": "id,name,access_token,instagram_business_account{id,username}",
        "access_token": user_access_token,
    }
    try:
        resp = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        raise AuthenticationError(f"Instagram /me/accounts request failed: {exc}") from exc

    data = _handle_response(resp, action="token_exchange")
    return data.get("data", [])


def verify_token(*, account: "ConnectedAccount") -> dict[str, Any]:
    """Verify the IG page access token via ``GET /me``.

    With a Page access token, ``/me`` resolves to the Facebook Page
    node, so we request ``id,name`` (the Page's identity). The
    ``username`` field is deprecated on this node (Graph API error
    code 12) and must not be requested. Returns the Page's
    ``{id, name}`` on success; raises ``AuthenticationError`` on any
    non-2xx response.
    """
    url = f"{GRAPH_API_BASE}/me"
    params = {"fields": "id,name", "access_token": _ig_token(account)}
    try:
        resp = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        raise AuthenticationError(f"Instagram verify request failed: {exc}") from exc
    return _handle_response(resp, action="verify")


def _handle_response(resp: requests.Response, *, action: str) -> dict[str, Any]:
    """Parse a Graph API response, raising SendMessageError on failure.

    Instagram uses the same error envelope as the rest of the Graph API:
    ``{"error": {"message", "type", "code", "fbtrace_id"}}``.
    """
    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text}

    if resp.status_code >= 400:
        err = (data or {}).get("error", {}) if isinstance(data, dict) else {}
        code = str(err.get("code", resp.status_code))
        message = err.get("message", resp.text[:300])
        if action in ("token_exchange", "verify"):
            raise AuthenticationError(f"Instagram {action} failed: {message}")
        raise SendMessageError(f"Instagram {action} failed: {message}", code=code)
    return data
