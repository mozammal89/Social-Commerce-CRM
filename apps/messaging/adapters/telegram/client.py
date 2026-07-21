"""
Telegram Bot API HTTP client.

Telegram bots are addressed by a single secret ``bot_token`` (issued by
``@BotFather``) baked into every API URL:

    https://api.telegram.org/bot<token>/<method>

There is no OAuth flow and no separate "page id"; the bot identity is
derived from the token's numeric prefix (``<bot_id>:<...>``).

References (Bot API):
* sendMessage:    POST /bot<token>/sendMessage
* sendPhoto:      POST /bot<token>/sendPhoto
* sendDocument:   POST /bot<token>/sendDocument
* sendAudio:      POST /bot<token>/sendAudio
* sendVideo:      POST /bot<token>/sendVideo
* sendLocation:   POST /bot<token>/sendLocation
* sendSticker:    POST /bot<token>/sendSticker
* getChat:        POST /bot<token>/getChat
* getMe:          POST /bot<token>/getMe     (verify_credentials)

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

BOT_API_BASE = "https://api.telegram.org"
DEFAULT_TIMEOUT = 20  # seconds


def _creds(account: "ConnectedAccount") -> dict[str, Any]:
    """Return the credentials dict for an account.

    Telegram credentials are small and rarely encrypted-string-shaped,
    but we still defend against legacy encodings for parity with the
    other adapters.
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
                "Failed to decrypt Telegram credentials for account %s: %s",
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


def _bot_token(account: "ConnectedAccount") -> str:
    """Read the bot token from the (decrypted) credentials."""
    token = _creds(account).get("bot_token", "")
    if not token:
        raise SendMessageError("Connected Telegram account has no bot_token.", code="missing_token")
    return token


def _call(
    *,
    account: "ConnectedAccount",
    method: str,
    data: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Invoke a Bot API method and return the parsed JSON response.

    Uses ``data=`` (form-encoded) rather than ``json=`` because the
    media-upload endpoints require multipart form data; mixing the two
    in a single client keeps the code simple.
    """
    token = _bot_token(account)
    url = f"{BOT_API_BASE}/bot{token}/{method}"
    logger.debug("Telegram API call: method=%s, data=%s", method, data)
    try:
        # ``json`` is sent alongside form fields when uploading media
        # (Telegram supports a ``parse_mode`` field for text). Keep it
        # simple: if there are no files, send as JSON so nested values
        # (like ``reply_markup``) are encoded automatically.
        if files:
            resp = requests.post(url, data=data, files=files, timeout=DEFAULT_TIMEOUT)
        else:
            resp = requests.post(url, json=data, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException as exc:
        raise SendMessageError(
            f"Telegram {method} request failed: {exc}", code="transport_error"
        ) from exc

    logger.debug(
        "Telegram API response: method=%s, status=%s, body=%s",
        method,
        resp.status_code,
        resp.text[:500],
    )
    return _handle_response(resp, action=method)


# ---------------------------------------------------------------------------
# Send endpoints — one per content type (Telegram requires distinct methods)
# ---------------------------------------------------------------------------
def send_message(
    *,
    account: "ConnectedAccount",
    chat_id: str | int,
    text: str,
    reply_to_message_id: int | None = None,
    parse_mode: str = "",
) -> dict[str, Any]:
    data: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if parse_mode:
        data["parse_mode"] = parse_mode
    if reply_to_message_id:
        data["reply_to_message_id"] = reply_to_message_id
    return _call(account=account, method="sendMessage", data=data)


def send_media(
    *,
    account: "ConnectedAccount",
    chat_id: str | int,
    method: str,
    media_field: str,
    url: str,
    caption: str = "",
    reply_to_message_id: int | None = None,
) -> dict[str, Any]:
    """Send a media message (photo/audio/document/video/sticker) by URL.

    Telegram accepts a publicly reachable URL via the ``<media_field>``
    field of the corresponding ``send<Media>`` method.
    """
    data: dict[str, Any] = {"chat_id": chat_id, media_field: url}
    if caption:
        data["caption"] = caption
    if reply_to_message_id:
        data["reply_to_message_id"] = reply_to_message_id
    return _call(account=account, method=method, data=data)


def send_location(
    *,
    account: "ConnectedAccount",
    chat_id: str | int,
    latitude: float,
    longitude: float,
) -> dict[str, Any]:
    return _call(
        account=account,
        method="sendLocation",
        data={"chat_id": chat_id, "latitude": latitude, "longitude": longitude},
    )


# ---------------------------------------------------------------------------
# Identity / profile
# ---------------------------------------------------------------------------
def get_chat(*, account: "ConnectedAccount", chat_id: str | int) -> dict[str, Any]:
    """Look up a chat's public profile via ``getChat``.

    For private chats this returns the user's ``first_name``, ``last_name``,
    ``username``, ``bio`` (when shared) and ``profile_photos`` info. For
    groups/channels it returns group metadata. Best-effort — returns
    ``{}`` on any failure (Telegram hides profiles of users who haven't
    messaged the bot).
    """
    try:
        data = _call(account=account, method="getChat", data={"chat_id": chat_id})
    except SendMessageError as exc:
        logger.info("Telegram getChat failed for chat_id=%s: %s", chat_id, exc)
        return {}
    return data.get("result", {}) if isinstance(data, dict) else {}


def get_me(*, account: "ConnectedAccount") -> dict[str, Any]:
    """Verify the bot token via ``getMe`` — the canonical Telegram check.

    Returns the bot's ``{id, username, first_name}`` on success; raises
    ``AuthenticationError`` on any non-OK response (invalid token, wrong
    format, etc.).
    """
    try:
        data = _call(account=account, method="getMe")
    except SendMessageError as exc:
        raise AuthenticationError(str(exc)) from exc
    return data.get("result", {}) if isinstance(data, dict) else {}


def _handle_response(resp: requests.Response, *, action: str) -> dict[str, Any]:
    """Parse a Bot API response, raising SendMessageError on failure.

    Telegram's response envelope is uniform::

        {"ok": true|false,
         "error_code": 400,           # HTTP-ish status (when ok=false)
         "description": "Bad Request: ...",
         "result": {...}}             # present when ok=true
    """
    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text}

    if not isinstance(data, dict) or not data.get("ok"):
        code = str(
            (data or {}).get("error_code", resp.status_code)
            if isinstance(data, dict)
            else resp.status_code
        )
        message = (
            (data or {}).get("description", resp.text[:300])
            if isinstance(data, dict)
            else resp.text[:300]
        )
        # 401 from Telegram means an invalid/expired bot token — surface
        # as an authentication error so the account is marked expired.
        if action == "getMe" or code == "401":
            raise AuthenticationError(f"Telegram {action} failed: {message}")
        raise SendMessageError(f"Telegram {action} failed: {message}", code=code)
    return data
