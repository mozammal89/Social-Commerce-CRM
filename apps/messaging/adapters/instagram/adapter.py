"""
Instagram Direct channel adapter.

Implements ``BaseChannelAdapter`` for Instagram DMs, which are delivered
through Meta's Messenger Platform on the Graph API. Because the wire
format is nearly identical to Facebook, this adapter follows the same
flow (verify → parse → send → enrich → connect), with these key
differences encoded here rather than leaking into the service layer:

* Webhook envelope uses ``object == "instagram"``.
* Send-API node is the **Instagram account id** (``ig-user-id``),
  not a FB Page id.
* Recipient ids are **IGSIDs** (Instagram-scoped ids).
* Profile fields are Instagram-specific (``username``, ``profile_pic``).

Credentials shape (stored encrypted on ConnectedAccount.credentials):
    {
        "app_id": "...",
        "app_secret": "...",          # used for webhook HMAC verification
        "page_access_token": "...",   # long-lived Page token (IG-permissioned)
        "ig_user_id": "...",          # == ConnectedAccount.external_id
        # Optional (when the user connected via OAuth rather than pasting
        # a page token directly) — used by refresh_credentials:
        "user_access_token": "...",
        "user_token_obtained_at": "...",
        "user_token_expires_at": "..."
    }
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from django.utils import timezone

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


@register("instagram")
class InstagramAdapter(BaseChannelAdapter):
    """Adapter for Instagram Direct via the Messenger Platform."""

    channel_type = "instagram"

    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------
    def verify_webhook(self, *, method, headers, query_params, body, account) -> tuple[bool, Any]:
        app_secret = (self._cred(account, "app_secret") or "").strip()
        if not app_secret:
            logger.error(
                "Instagram webhook verification failed for account %s (%s): app_secret is empty or "
                "missing. Credentials keys available: %s",
                account.id,
                account.name,
                list((account.credentials or {}).keys())
                if isinstance(account.credentials, dict)
                else "not_a_dict",
            )
        verify_token = account.webhook_verify_token or self._cred(account, "verify_token")
        ok, challenge = webhook.verify(
            query_params=query_params,
            body=body,
            headers=headers,
            app_secret=app_secret,
            verify_token=verify_token,
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

        payload = self._build_send_payload(recipient_external_id, message)
        logger.debug("Sending Instagram message: payload=%s", payload)
        try:
            data = client.send(
                account=account, recipient_igsid=recipient_external_id, payload=payload
            )
            logger.info("Instagram send successful: data=%s", data)
        except SendMessageError as exc:
            logger.error("Instagram send failed: %s (code=%s)", exc, exc.code)
            return SendResult(
                success=False,
                status=DeliveryStatus.FAILED.value,
                error_code=exc.code,
                error_message=str(exc),
            )

        # Send API returns {"recipient_id": "...", "message_id": "..."}
        external_id = (data or {}).get("message_id") or (data or {}).get("id")
        return SendResult(
            success=True,
            external_id=external_id,
            status=DeliveryStatus.SENT.value,
            raw=data,
        )

    def _build_send_payload(self, igsid: str, message: OutboundMessage) -> dict[str, Any]:
        """Translate OutboundMessage into an IG Graph Send API payload.

        IG Send API requires ``recipient.id`` to be the IGSID. The
        ``message`` block mirrors FB's (text + optional attachment).
        ``messaging_type`` defaults to ``RESPONSE`` (within the 24h
        window) — callers can override via ``message.extra``.
        """
        msg: dict[str, Any] = {}
        if message.text:
            msg["text"] = message.text

        for att in message.attachments:
            attachment = self._build_attachment(att.attachment_type, att.url or "")
            if attachment:
                # IG Send API supports a single attachment per message.
                msg.setdefault("attachment", attachment)
                break

        return {
            "recipient": {"id": igsid},
            "message": msg,
            "messaging_type": message.extra.get("messaging_type", "RESPONSE"),
        }

    def _build_attachment(self, attachment_type: str, url: str) -> dict | None:
        """Build a single IG attachment payload. URL-based only for now."""
        if not url:
            return None
        ig_type = {
            MessageType.IMAGE.value: "image",
            MessageType.AUDIO.value: "audio",
            MessageType.VIDEO.value: "video",
            MessageType.FILE.value: "file",
        }.get(attachment_type, "file")
        return {"type": ig_type, "payload": {"url": url}}

    # ------------------------------------------------------------------
    # Identity / profile
    # ------------------------------------------------------------------
    def fetch_identity_profile(self, *, account, external_id) -> dict[str, Any]:
        """Fetch the Instagram profile for an IGSID.

        Instagram Messaging only exposes ``name`` and ``profile_pic``
        for a sender (the ``/{igsid}`` node). The ``username``,
        ``followers_count`` and ``media_count`` fields are NOT
        available for messaging senders — requesting them raises
        Graph API error code 12. We fall back to the IGSID for the
        display name when ``name`` is empty so the agent always sees
        something. Locale/timezone are not exposed by Instagram.
        """
        profile = client.fetch_profile(account=account, igsid=external_id)
        name = profile.get("name", "")
        return {
            "display_name": name or external_id,
            "avatar_url": profile.get("profile_pic", ""),
            "first_name": "",
            "last_name": "",
            "language": "",
            "timezone": "",
            "extra": profile,
        }

    # ------------------------------------------------------------------
    # Account connection
    # ------------------------------------------------------------------
    def authenticate_account(self, *, account, credentials) -> dict[str, Any]:
        """Normalize freshly-supplied Instagram credentials.

        Instagram DMs use the same Meta OAuth flow as Facebook Messenger:

        1. If a **short-lived user token** is supplied, exchange it for
           a long-lived user token (~60 days).
        2. Use the long-lived user token to fetch the IG-connected
           Page's long-lived Page access token via ``GET /me/accounts``
           (with ``instagram_business_account`` field). The Page token
           carries the ``instagram_manage_messages`` permission needed
           to send DMs.
        3. Store both tokens + expiry metadata so the periodic refresh
           task can re-fetch the page token before the user token lapses.

        If a ready ``page_access_token`` is supplied directly, it is
        stored as-is — but without a user token it cannot be auto-
        refreshed; it will be marked ``expired`` when it dies.
        """
        app_id = (credentials.get("app_id") or self._cred(account, "app_id") or "").strip()
        app_secret = (
            credentials.get("app_secret") or self._cred(account, "app_secret") or ""
        ).strip()
        page_token = (credentials.get("page_access_token") or "").strip()
        ig_user_id = (credentials.get("ig_user_id") or account.external_id or "").strip()

        if not app_id or not app_secret:
            raise ConfigurationError("Instagram connection requires app_id and app_secret.")

        now = timezone.now()
        normalized: dict[str, Any] = {
            "app_id": app_id,
            "app_secret": app_secret,
            "ig_user_id": ig_user_id,
        }

        # --- Path A: short-lived user token -> long-lived -> page token ---
        short = credentials.get("short_lived_token")
        user_token = credentials.get("long_lived_user_token")

        if short and not page_token:
            exchanged = client.exchange_long_lived_token(
                app_id=app_id, app_secret=app_secret, short_lived_token=short
            )
            user_token = exchanged.get("access_token", "")
            expires_in = exchanged.get("expires_in")
            if expires_in:
                normalized["user_token_expires_at"] = (
                    now + timedelta(seconds=int(expires_in))
                ).isoformat()

        # --- Path B: raw page_access_token pasted directly ---
        # The user often pastes a short-lived USER token from the Meta
        # App Dashboard thinking it's a page token. Try to exchange it;
        # if that succeeds, fetch a real long-lived page token.
        if page_token and not user_token and not short:
            try:
                exchanged = client.exchange_long_lived_token(
                    app_id=app_id,
                    app_secret=app_secret,
                    short_lived_token=page_token,
                )
                user_token = exchanged.get("access_token", "")
                expires_in = exchanged.get("expires_in")
                if expires_in:
                    normalized["user_token_expires_at"] = (
                        now + timedelta(seconds=int(expires_in))
                    ).isoformat()
                logger.info(
                    "authenticate_account: raw page_access_token was a user token — "
                    "exchanged + fetching IG page token."
                )
            except AuthenticationError:
                logger.debug(
                    "authenticate_account: page_access_token could not be exchanged — "
                    "using as-is (likely already a page token)."
                )

        # If we have a long-lived user token, fetch the IG-connected
        # Page token via /me/accounts (with instagram_business_account).
        if user_token:
            normalized["user_access_token"] = user_token
            normalized["user_token_obtained_at"] = now.isoformat()
            pages = client.fetch_page_tokens(user_access_token=user_token)
            page = self._pick_ig_page(pages, ig_user_id)
            if page:
                page_token = page.get("access_token", page_token or "")
                ig_account = page.get("instagram_business_account") or {}
                if not ig_user_id and ig_account.get("id"):
                    ig_user_id = ig_account["id"]
                    normalized["ig_user_id"] = ig_user_id
                normalized["page_token_obtained_at"] = now.isoformat()

        if not page_token:
            raise AuthenticationError(
                "Instagram connection requires a page_access_token "
                "(or a short_lived_token to derive one)."
            )

        normalized["page_access_token"] = page_token
        return normalized

    def verify_credentials(self, *, account) -> VerifyResult:
        """Check the page access token against the Graph API (``GET /me``).

        With a Page token, ``/me`` returns the Page node's ``id`` and
        ``name`` — we surface the Page name as the account's display
        name. The ``username`` field is deprecated on this endpoint
        (Graph API error code 12) and is never requested.
        """
        try:
            data = client.verify_token(account=account)
        except AuthenticationError as exc:
            return VerifyResult(valid=False, error_code="auth_failed", error_message=str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            return VerifyResult(valid=False, error_code="error", error_message=str(exc))
        return VerifyResult(
            valid=True,
            account_name=data.get("name", ""),
            external_id=data.get("id", ""),
            raw=data,
        )

    # ------------------------------------------------------------------
    # Token lifecycle — refresh
    # ------------------------------------------------------------------
    def refresh_credentials(self, *, account) -> bool:
        """Refresh the stored IG page access token.

        If we hold a long-lived **user** token, re-fetch a fresh IG-
        connected Page token via ``GET /me/accounts`` and persist it.
        Returns ``True`` when updated, ``False`` when no refresh was
        possible (no user token).
        """
        user_token = self._cred(account, "user_access_token")
        if not user_token:
            return False

        ig_user_id = self._cred(account, "ig_user_id") or (account.external_id or "")
        pages = client.fetch_page_tokens(user_access_token=user_token)
        page = self._pick_ig_page(pages, ig_user_id)
        if not page:
            raise AuthenticationError(
                "Instagram user token is valid but manages no IG-connected pages."
            )

        new_token = page.get("access_token", "")
        if not new_token:
            raise AuthenticationError("Instagram /me/accounts returned no access_token.")

        now = timezone.now()
        creds = client._creds_dict(account)
        creds["page_access_token"] = new_token
        creds["user_access_token"] = user_token
        creds["page_token_obtained_at"] = now.isoformat()
        account.credentials = creds
        account.save(update_fields=["credentials", "updated_at"])
        logger.info("Refreshed Instagram page access token for account %s", account.id)
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _pick_ig_page(pages: list[dict[str, Any]], ig_user_id: str) -> dict[str, Any] | None:
        """Pick the FB Page whose linked IG account matches ``ig_user_id``.

        When ``ig_user_id`` is unknown, fall back to the first page that
        has a linked Instagram account. Returns ``None`` if no page is
        IG-connected.
        """
        if not pages:
            return None
        for p in pages:
            ig = p.get("instagram_business_account") or {}
            ig_id = str(ig.get("id") or "")
            if ig_user_id and ig_id == str(ig_user_id):
                return p
        # No explicit match — pick the first page that has an IG link.
        return next(
            (p for p in pages if p.get("instagram_business_account")),
            pages[0],
        )

    def _cred(self, account: "ConnectedAccount", key: str, default: str = "") -> str:
        """Safely extract a credential value from the account's credentials.

        Handles the encrypted-ciphertext / JSON-string / dict shapes the
        EncryptedJSONField may produce. Reads via ``client._creds_dict``
        so the parsing logic is shared with the client.
        """
        creds = client._creds_dict(account)
        return creds.get(key, default) or default
