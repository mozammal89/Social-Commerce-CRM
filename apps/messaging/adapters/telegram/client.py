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
    account: "ConnectedAccount | None" = None,
    method: str,
    data: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    bot_token: str = "",
) -> dict[str, Any]:
    """Invoke a Bot API method and return the parsed JSON response.

    Uses ``data=`` (form-encoded) rather than ``json=`` because the
    media-upload endpoints require multipart form data; mixing the two
    in a single client keeps the code simple.

    The bot token is resolved from ``bot_token`` (explicit override,
    used during connect before the account is persisted) or from the
    account's credentials.
    """
    token = bot_token or _bot_token(account) if account else bot_token
    if not token:
        raise SendMessageError(
            "Telegram API call requires either an account with bot_token "
            "or an explicit bot_token argument.",
            code="missing_token",
        )
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


def get_file(
    *, account: "ConnectedAccount | None" = None, file_id: str, bot_token: str = ""
) -> dict[str, Any]:
    """Fetch metadata (including ``file_path``) for a Telegram file via ``getFile``.

    Telegram media (photos, documents, voice, etc.) only carries a
    ``file_id`` in webhook payloads — you must call ``getFile`` to
    resolve the download path. Returns ``{}`` on failure (best-effort).

    Accepts either a persisted account or an explicit ``bot_token``.
    """
    try:
        data = _call(
            account=account, method="getFile", data={"file_id": file_id}, bot_token=bot_token
        )
    except SendMessageError as exc:
        logger.info("Telegram getFile failed for file_id=%s: %s", file_id[:20], exc)
        return {}
    return data.get("result", {}) if isinstance(data, dict) else {}


def get_file_url(
    *, account: "ConnectedAccount | None" = None, file_id: str, bot_token: str = ""
) -> str:
    """Resolve a Telegram ``file_id`` to a publicly downloadable URL.

    Two-step process (per Bot API docs):
    1. ``getFile`` → returns ``{file_path: "photos/file_1.jpg", ...}``
    2. Construct URL: ``https://api.telegram.org/file/bot<token>/<file_path>``

    Returns ``""`` on failure so callers can degrade gracefully.
    """
    token = bot_token or _creds(account).get("bot_token", "") if account else bot_token
    if not token or not file_id:
        return ""
    result = get_file(account=account, file_id=file_id, bot_token=bot_token)
    file_path = result.get("file_path", "")
    if not file_path:
        return ""
    return f"{BOT_API_BASE}/file/bot{token}/{file_path}"


def get_user_profile_photo_url(
    *,
    account: "ConnectedAccount",
    user_id: str | int,
) -> str:
    """Fetch a user's profile photo URL via ``getUserProfilePhotos`` + ``getFile``.

    ``getChat`` does NOT return profile photo data for private chats.
    This two-step call fetches the most recent photo's ``file_id`` and
    resolves it to a downloadable URL. Best-effort — returns ``""``
    when the user has no profile photo or the bot lacks access.
    """
    try:
        data = _call(
            account=account,
            method="getUserProfilePhotos",
            data={"user_id": user_id, "limit": 1},
        )
    except SendMessageError as exc:
        logger.info("Telegram getUserProfilePhotos failed for user=%s: %s", user_id, exc)
        return ""
    result = data.get("result", {}) if isinstance(data, dict) else {}
    photos = result.get("photos", [])
    if not photos:
        return ""
    # photos is [[PhotoSize, ...], ...] — pick the largest from the first set.
    sizes = photos[0]
    if not sizes:
        return ""
    # Largest size is last in the array (Telegram sorts by resolution).
    file_id = sizes[-1].get("file_id", "")
    if not file_id:
        return ""
    return get_file_url(account=account, file_id=file_id)


def set_webhook(
    *,
    account: "ConnectedAccount | None" = None,
    webhook_url: str,
    secret_token: str = "",
    bot_token: str = "",
) -> dict[str, Any]:
    """Register (or update) the bot's webhook URL via ``setWebhook``.

    Called after the account is saved so we can construct the full
    per-account webhook URL. ``drop_pending_updates=True`` clears any
    backlog from before the webhook was set.
    """
    data: dict[str, Any] = {
        "url": webhook_url,
        "drop_pending_updates": True,
    }
    if secret_token:
        data["secret_token"] = secret_token
    return _call(account=account, method="setWebhook", data=data, bot_token=bot_token)


def get_me(
    *,
    account: "ConnectedAccount | None" = None,
    bot_token: str = "",
) -> dict[str, Any]:
    """Verify the bot token via ``getMe`` — the canonical Telegram check.

    Returns the bot's ``{id, username, first_name}`` on success; raises
    ``AuthenticationError`` on any non-OK response (invalid token, wrong
    format, etc.). Accepts either a persisted account or an explicit
    ``bot_token`` (used during connect before the account is saved).
    """
    try:
        data = _call(account=account, method="getMe", bot_token=bot_token)
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
