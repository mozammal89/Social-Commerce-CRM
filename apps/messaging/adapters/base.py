"""
Base channel adapter — the contract every messaging platform implements.

Design (Open/Closed + Dependency Inversion)
-------------------------------------------
The service layer depends on ``BaseChannelAdapter`` (this abstraction),
never on a concrete ``FacebookAdapter`` or ``WhatsAppAdapter``. Adding a
new platform means:

1. Subclass ``BaseChannelAdapter`` and set ``channel_type``.
2. Implement the abstract methods (webhook verification/parsing, sending,
   identity lookup, account authentication).
3. Register it with ``@register("<channel_type>")``.

The core models, services and realtime layer then work with the new
channel **unchanged**. Services hand adapters normalized DTOs
(``OutboundMessage``) and receive normalized DTOs back
(``NormalizedIncomingEvent`` / ``DeliveryUpdate``) — platform JSON never
leaves the adapter.

Adapters are instantiated per-call (see ``registry.get_adapter``) and
receive the ``ConnectedAccount`` they operate on, so they are stateless
and safe to use across threads/requests.
"""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Any

from .dto import (
    DeliveryUpdate,
    NormalizedIncomingEvent,
    OutboundMessage,
    SendResult,
    VerifyResult,
)

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from ..models import ConnectedAccount


class BaseChannelAdapter(abc.ABC):
    """Abstract base for all channel adapters.

    Subclasses set ``channel_type`` (matching a ``ChannelType`` value)
    and implement the abstract methods. Concrete adapters live in
    platform subpackages (e.g. ``apps/messaging/adapters/facebook/``).
    """

    #: Stable identifier matching ``Channel.channel_type`` and the
    #: registry key. Subclasses MUST override this.
    channel_type: str = ""

    # ------------------------------------------------------------------
    # Webhook ingestion (platform -> CRM)
    # ------------------------------------------------------------------
    @abc.abstractmethod
    def verify_webhook(
        self,
        *,
        method: str,
        headers: dict[str, str],
        query_params: dict[str, str],
        body: bytes,
        account: "ConnectedAccount",
    ) -> tuple[bool, Any]:
        """Validate the inbound webhook request.

        Returns ``(ok, response_payload)``:

        * For GET subscription verification (e.g. Facebook's
          ``hub.challenge`` handshake), ``ok`` is True and
          ``response_payload`` is the challenge string to echo back.
        * For POST event delivery, ``ok`` indicates whether the
          signature / verify-token check passed; ``response_payload``
          is unused (the caller returns 200 regardless to acknowledge
          the webhook fast).
        * When ``ok`` is False the caller returns 403.
        """

    @abc.abstractmethod
    def parse_webhook(
        self,
        *,
        headers: dict[str, str],
        body: bytes,
        account: "ConnectedAccount",
    ) -> list[NormalizedIncomingEvent | DeliveryUpdate]:
        """Parse a verified webhook body into normalized events.

        A single platform payload may contain multiple messages or a
        mix of messages and status receipts; return them all. Invalid
        or unsupported entries should be skipped (and logged) rather
        than raising — one bad event must not drop the whole batch.
        """

    # ------------------------------------------------------------------
    # Sending (CRM -> platform)
    # ------------------------------------------------------------------
    @abc.abstractmethod
    def send_message(
        self,
        *,
        account: "ConnectedAccount",
        recipient_external_id: str,
        message: OutboundMessage,
    ) -> SendResult:
        """Send an outbound message via the platform's send API.

        Implementations should translate ``message`` into the platform
        payload, call the API, and return a ``SendResult``. Network /
        API errors raise ``SendMessageError`` (caught by the service
        layer, which marks the message FAILED).
        """

    # ------------------------------------------------------------------
    # Identity / profile enrichment
    # ------------------------------------------------------------------
    @abc.abstractmethod
    def fetch_identity_profile(
        self,
        *,
        account: "ConnectedAccount",
        external_id: str,
    ) -> dict[str, Any]:
        """Fetch the platform-side profile for a customer id.

        Returns a dict with the following keys. Adapters MUST include all
        keys, using empty strings when the platform does not expose the
        field — never raise on "profile not found", return an empty-ish
        dict so profile enrichment is always best-effort.

        Required keys:
            display_name : str   — human name or "" (fall back to external_id
                                   at the service layer if empty)
            avatar_url   : str   — public URL or "" (e.g. FB profile_pic)
            first_name   : str   — "" if the platform only returns a full name
            last_name    : str   — "" if the platform only returns a full name
            language     : str   — ISO 639-1 code (e.g. "en") or "" if unknown.
                                   Channels exposing a full locale (e.g. FB's
                                   "en_US") should extract the language part.
            timezone     : str   — IANA name (e.g. "America/New_York") when
                                   available, a UTC offset string (e.g.
                                   "UTC-05:00") when the channel only exposes
                                   an offset, or "" if unknown.
            extra        : dict  — the full raw profile payload, kept for
                                   debugging/audit. Always a dict ({} when
                                   nothing was fetched).

        Channel capability matrix:
            Facebook Messenger — name, avatar via GET /{psid}; locale + numeric
                                 tz offset available with user_profile permission
            WhatsApp Cloud API — name only (via contacts lookup); no avatar,
                                 no locale, no timezone
            Instagram          — username, name, profile pic (future)
            Telegram           — first/last name, username, language_code (future)
        """

    # ------------------------------------------------------------------
    # Account connection / lifecycle
    # ------------------------------------------------------------------
    @abc.abstractmethod
    def authenticate_account(
        self,
        *,
        account: "ConnectedAccount",
        credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate exchanged credentials and return normalized ones.

        Given a freshly-authorized account and the raw credentials
        (OAuth code, short-lived token, etc.), perform any token
        exchange/long-lived-token conversion and return the
        **normalized** credentials dict to store (encrypted) on the
        account. Raise ``AuthenticationError`` on failure.
        """

    def verify_credentials(self, *, account: "ConnectedAccount") -> "VerifyResult":
        """Check the stored credentials against the platform.

        Makes a lightweight authenticated API call (e.g. FB ``GET /me``,
        WA ``GET /{phone_number_id}``) to confirm the token works and the
        page/number is reachable. Returns a ``VerifyResult`` with the
        platform-confirmed name and id. The default implementation skips
        gracefully (returns ``valid=True``) so channels without a real
        adapter don't block connection — concrete adapters override this.

        Called by the service layer after ``connect_account`` (to validate
        on connect) and on demand via the "Test connection" UI button.
        """
        return VerifyResult(
            valid=True, raw={"note": "verify_credentials not implemented for this channel"}
        )

    def refresh_credentials(self, *, account: "ConnectedAccount") -> bool:
        """Refresh expiring credentials (e.g. FB long-lived tokens).

        Returns ``True`` if the credentials were refreshed and persisted,
        ``False`` if no refresh was needed or possible. Raises
        ``AuthenticationError`` when refresh is attempted but fails
        irreversibly — the caller (the periodic Celery task) treats that
        as "mark the account expired".

        Default no-op; adapters with expiring tokens override this.
        """
        return False
