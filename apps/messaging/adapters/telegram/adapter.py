"""
Telegram channel adapter.

Implements ``BaseChannelAdapter`` for the Telegram Bot API. Telegram is
fundamentally different from the Meta-based channels:

* There is **no OAuth flow**. A bot is created once via ``@BotFather``
  and issued a ``bot_token`` of the form ``<bot_id>:<auth_token>``. The
  token is the entire credential.
* Webhook verification is via an optional **secret_token** echoed in
  the ``X-Telegram-Bot-Api-Secret-Token`` header — not an HMAC body
  signature.
* The webhook URL is set out-of-band via the Bot API's ``setWebhook``
  method, called here in ``authenticate_account`` so connecting a bot
  also wires up its webhook.
* Send endpoints are **per-content-type** (``sendMessage``,
  ``sendPhoto``, ``sendDocument``, ...) rather than one endpoint with a
  type-tagged payload.

Credentials shape (stored encrypted on ConnectedAccount.credentials):
    {
        "bot_token": "...",          # full "<bot_id>:<auth>" from BotFather
        "secret_token": "...",       # optional, for webhook verification
        "bot_id": "12345",           # parsed from bot_token prefix
        "bot_username": "...",       # without the leading @
    }

``ConnectedAccount.external_id`` holds the bot's numeric Telegram user
id (parsed from the token prefix), so one bot = one connected account.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..base import BaseChannelAdapter
from ..dto import (
    DeliveryUpdate,
    NormalizedIncomingEvent,
    OutboundMessage,
    SendResult,
    VerifyResult,
)
from ..exceptions import AuthenticationError, ConfigurationError, SendMessageError
from ..registry import register
from . import client, webhook
from ...constants import DeliveryStatus, MessageType

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from ...models import ConnectedAccount

logger = logging.getLogger(__name__)

# Map our internal attachment types → Telegram send-method + field name.
# Telegram requires a different endpoint per media type.
_TELEGRAM_MEDIA_METHODS = {
    MessageType.IMAGE.value: ("sendPhoto", "photo"),
    MessageType.AUDIO.value: ("sendAudio", "audio"),
    MessageType.VIDEO.value: ("sendVideo", "video"),
    MessageType.DOCUMENT.value: ("sendDocument", "document"),
    MessageType.FILE.value: ("sendDocument", "document"),
}


@register("telegram")
class TelegramAdapter(BaseChannelAdapter):
    """Adapter for Telegram via the Bot API."""

    channel_type = "telegram"

    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------
    def verify_webhook(self, *, method, headers, query_params, body, account) -> tuple[bool, Any]:
        secret_token = self._cred(account, "secret_token")
        ok, challenge = webhook.verify(
            method=method,
            query_params=query_params,
            body=body,
            headers=headers,
            secret_token=secret_token,
        )
        return ok, challenge

    def parse_webhook(
        self, *, headers, body, account
    ) -> list[NormalizedIncomingEvent | DeliveryUpdate]:
        return webhook.parse(body=body)

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------
    def send_message(self, *, account, recipient_external_id, message) -> SendResult:
        if not message.has_content:
            return SendResult(
                success=False,
                status=DeliveryStatus.FAILED.value,
                error_message="Empty message",
            )

        # ``recipient_external_id`` is the customer's Telegram user id.
        # Telegram chat ids are integers; we accept either the raw int
        # form or a string — the Bot API accepts both.
        chat_id = self._normalize_chat_id(recipient_external_id)

        try:
            data = self._dispatch_send(account, chat_id, message)
        except SendMessageError as exc:
            logger.error("Telegram send failed: %s (code=%s)", exc, exc.code)
            return SendResult(
                success=False,
                status=DeliveryStatus.FAILED.value,
                error_code=exc.code,
                error_message=str(exc),
            )

        # Telegram returns {"result": {"message_id": 42, ...}}
        result = (data or {}).get("result") or {}
        external_msg_id = result.get("message_id")
        external_id = f"tg:{chat_id}:{external_msg_id}" if external_msg_id is not None else None
        return SendResult(
            success=True,
            external_id=external_id,
            status=DeliveryStatus.SENT.value,
            raw=data,
        )

    def _dispatch_send(
        self,
        account: "ConnectedAccount",
        chat_id: str | int,
        message: OutboundMessage,
    ) -> dict[str, Any]:
        """Pick the right Bot API endpoint and call it.

        Telegram requires one endpoint per content type, so we look at
        the first attachment's type and dispatch. Text + caption ride
        alongside the media (``caption`` field) when present.
        """
        # Reply context — Telegram uses the message id directly. We
        # strip our chat-id prefix to recover the raw int.
        reply_to_id = self._strip_chat_prefix(message.reply_to_external_id)

        if message.attachments:
            att = message.attachments[0]
            method_field = _TELEGRAM_MEDIA_METHODS.get(att.attachment_type)
            if method_field is None:
                # Unknown media type — fall back to document.
                method_field = ("sendDocument", "document")
            method, field = method_field
            url = att.url or ""
            if not url:
                raise SendMessageError(
                    "Telegram media send requires a public attachment URL.",
                    code="missing_url",
                )
            return client.send_media(
                account=account,
                chat_id=chat_id,
                method=method,
                media_field=field,
                url=url,
                caption=message.text,
                reply_to_message_id=reply_to_id,
            )

        # Plain text — ``message_type == LOCATION`` is the only special
        # case (it uses ``sendLocation`` and ignores ``text``).
        if message.message_type == MessageType.LOCATION.value and message.extra.get("location"):
            loc = message.extra["location"]
            return client.send_location(
                account=account,
                chat_id=chat_id,
                latitude=float(loc["latitude"]),
                longitude=float(loc["longitude"]),
            )

        # Default: text message. Allow ``parse_mode`` override via extra.
        parse_mode = message.extra.get("parse_mode", "")
        return client.send_message(
            account=account,
            chat_id=chat_id,
            text=message.text,
            reply_to_message_id=reply_to_id,
            parse_mode=parse_mode,
        )

    # ------------------------------------------------------------------
    # Identity / profile
    # ------------------------------------------------------------------
    def fetch_identity_profile(self, *, account, external_id) -> dict[str, Any]:
        """Fetch the Telegram profile for a user id.

        Telegram exposes ``first_name``, ``last_name``, ``username`` and
        ``language_code`` (ISO 639-1) via ``getChat`` for users who have
        messaged the bot. Avatars require a separate
        ``getUserProfilePhotos`` call (best-effort, omitted here — the
        ``extra`` block carries what ``getChat`` returned so the UI can
        lazy-load photos later). Timezone is never exposed by Telegram.
        """
        chat_id = self._normalize_chat_id(external_id)
        chat = client.get_chat(account=account, chat_id=chat_id)

        first = chat.get("first_name", "")
        last = chat.get("last_name", "")
        username = chat.get("username", "")
        full = f"{first} {last}".strip()
        display = full or (f"@{username}" if username else str(external_id))

        # Telegram's ``language_code`` is already an ISO 639-1 code.
        language = chat.get("language_code", "")

        return {
            "display_name": display,
            "avatar_url": "",  # not exposed by getChat; needs getUserProfilePhotos
            "first_name": first,
            "last_name": last,
            "language": language,
            "timezone": "",
            "extra": chat,
        }

    # ------------------------------------------------------------------
    # Account connection
    # ------------------------------------------------------------------
    def authenticate_account(self, *, account, credentials) -> dict[str, Any]:
        """Validate a Telegram bot token and wire up its webhook.

        Steps:

        1. Validate the ``bot_token`` format (``<id>:<secret>``).
        2. Call ``getMe`` to confirm the token is live and capture the
           bot's username/id (these become ``external_id`` /
           ``bot_username`` on the normalized credentials).
        3. If a ``webhook_url`` was supplied (the connect UI should pass
           the per-account webhook URL), call ``setWebhook`` so Telegram
           starts delivering updates to our endpoint. The optional
           ``secret_token`` is sent in the same call so subsequent
           deliveries can be verified.
        """
        bot_token = credentials.get("bot_token")
        if not bot_token:
            raise ConfigurationError("Telegram connection requires a bot_token.")

        normalized: dict[str, Any] = {
            "bot_token": bot_token,
            "secret_token": credentials.get("secret_token", ""),
        }

        # Parse the bot id from the token's numeric prefix.
        token_prefix = str(bot_token).split(":", 1)[0]
        if token_prefix.isdigit():
            normalized["bot_id"] = token_prefix
            # Surface as external_id hint when none was provided.
            if not account.external_id:
                account.external_id = token_prefix

        # Verify the token against Telegram.
        me = client.get_me(account=account)  # uses the transient account
        bot_username = me.get("username", "")
        bot_id = str(me.get("id") or token_prefix)
        normalized["bot_id"] = bot_id
        normalized["bot_username"] = bot_username
        if not account.external_id:
            account.external_id = bot_id

        # Wire up the webhook if a URL was provided. The connect UI is
        # expected to pass the full per-account webhook URL it wants
        # Telegram to POST to (typically
        # ``https://<host>/api/v1/messaging/webhooks/telegram/<account_id>/``).
        webhook_url = credentials.get("webhook_url")
        if webhook_url:
            self._set_webhook(
                account=account,
                webhook_url=webhook_url,
                secret_token=normalized["secret_token"],
            )
            normalized["webhook_url"] = webhook_url

        return normalized

    def verify_credentials(self, *, account) -> VerifyResult:
        """Check the bot token via ``getMe``.

        Confirms the token is valid and the bot is reachable, returning
        the bot's @username (used by the UI as the display name).
        """
        try:
            me = client.get_me(account=account)
        except AuthenticationError as exc:
            return VerifyResult(valid=False, error_code="auth_failed", error_message=str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            return VerifyResult(valid=False, error_code="error", error_message=str(exc))
        username = me.get("username", "")
        return VerifyResult(
            valid=True,
            account_name=f"@{username}" if username else (me.get("first_name") or ""),
            external_id=str(me.get("id", "")),
            raw=me,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _set_webhook(
        self,
        *,
        account: "ConnectedAccount",
        webhook_url: str,
        secret_token: str = "",
    ) -> None:
        """Register the webhook URL with Telegram via ``setWebhook``.

        Best-effort: failure is logged but does not block connect, so
        the user can still save credentials and configure the webhook
        manually via BotFather / the Telegram API console.
        """
        data: dict[str, Any] = {
            "url": webhook_url,
            "drop_pending_updates": True,
        }
        if secret_token:
            data["secret_token"] = secret_token
        try:
            client._call(account=account, method="setWebhook", data=data)
            logger.info("Telegram webhook set to %s", webhook_url)
        except SendMessageError as exc:
            logger.warning(
                "Telegram setWebhook failed (account=%s): %s — the bot will still "
                "save; configure the webhook manually.",
                account.id,
                exc,
            )

    @staticmethod
    def _normalize_chat_id(chat_id: str | int) -> int | str:
        """Coerce a chat id to int when possible (Telegram's preference).

        Stored channel identities may carry the id as a string (the
        ``EncryptedJSONField`` is JSON-backed), but Telegram's Bot API
        accepts ints natively.
        """
        if isinstance(chat_id, int):
            return chat_id
        s = str(chat_id).strip()
        # Strip any "tg:" prefix our webhook layer may have added.
        if ":" in s:
            s = s.split(":")[-1]
        # Negative ids are group/supergroup/channel ids — preserve sign.
        if s.lstrip("-").isdigit():
            return int(s)
        return s

    @staticmethod
    def _strip_chat_prefix(external_id: str) -> int | None:
        """Recover the raw Telegram ``message_id`` from our composite id.

        Our webhook layer stores replies as ``"tg:<chat_id>:<message_id>"``;
        Telegram needs just the trailing int for ``reply_to_message_id``.
        """
        if not external_id:
            return None
        parts = str(external_id).split(":")
        tail = parts[-1]
        if tail.lstrip("-").isdigit():
            return int(tail)
        return None

    def _cred(self, account: "ConnectedAccount", key: str, default: str = "") -> str:
        """Safely extract a credential value from the account."""
        return client._creds(account).get(key, default) or default
