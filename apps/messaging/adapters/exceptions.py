"""
Exception hierarchy for channel adapters.

Adapter errors are raised inside the adapter/platform boundary and
bubble up to services, which translate them into delivery failures
(for inbound/send flows) or HTTP error responses (for connection flows).
Keeping a dedicated hierarchy (rather than reusing DRF or RBAC
exceptions) lets services branch on adapter errors without importing
platform code.
"""

from __future__ import annotations


class AdapterError(Exception):
    """Base class for all adapter-related errors."""


class WebhookVerificationError(AdapterError):
    """Raised when a webhook signature/verify-token check fails.

    Surfaces as HTTP 403/401 to the platform; never exposes internals.
    """


class WebhookParseError(AdapterError):
    """Raised when an adapter cannot parse a (verified) webhook payload.

    Usually indicates an unexpected platform payload shape — log the raw
    payload for investigation but don't crash ingestion for other events.
    """


class SendMessageError(AdapterError):
    """Raised when sending an outbound message to a platform fails.

    Carries ``code`` so the service layer can store a structured
    ``error_code`` on the Message for later triage.
    """

    def __init__(self, message: str = "", *, code: str = "") -> None:
        super().__init__(message)
        self.code = code


class AuthenticationError(AdapterError):
    """Raised when OAuth/token exchange or credential validation fails."""


class ConfigurationError(AdapterError):
    """Raised when an adapter is misconfigured (missing app secret, etc.)."""
