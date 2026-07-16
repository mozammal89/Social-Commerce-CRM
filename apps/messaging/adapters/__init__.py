"""
Channel adapter package.

Platform-specific adapters (Facebook, WhatsApp, ...) live in
subpackages and register themselves with the registry via the
``@register`` decorator. Importing this package eagerly imports every
bundled adapter so they are registered on startup — both here and in
``MessagingConfig.ready()`` (which imports this package).

Re-exports the public adapter API so callers can do::

    from apps.messaging.adapters import get_adapter, register, BaseChannelAdapter
"""

from .base import BaseChannelAdapter
from .dto import (
    DeliveryUpdate,
    NormalizedAttachment,
    NormalizedIncomingEvent,
    NormalizedReactionEvent,
    OutboundAttachment,
    OutboundMessage,
    SendResult,
)
from .exceptions import (
    AdapterError,
    AuthenticationError,
    ConfigurationError,
    SendMessageError,
    WebhookParseError,
    WebhookVerificationError,
)
from .registry import (
    get_adapter,
    get_adapter_class,
    get_adapter_for_account,
    register,
    registered_channel_types,
)

# Eagerly import bundled adapters so they self-register. Done at the
# bottom (after the registry is importable) and guarded so a missing
# optional adapter never breaks the whole app.
from .registry import _import_adapters  # noqa: E402

_import_adapters()

__all__ = [
    # Base + DTOs
    "BaseChannelAdapter",
    "NormalizedAttachment",
    "NormalizedIncomingEvent",
    "NormalizedReactionEvent",
    "DeliveryUpdate",
    "OutboundAttachment",
    "OutboundMessage",
    "SendResult",
    # Exceptions
    "AdapterError",
    "AuthenticationError",
    "ConfigurationError",
    "SendMessageError",
    "WebhookParseError",
    "WebhookVerificationError",
    # Registry
    "register",
    "get_adapter",
    "get_adapter_class",
    "get_adapter_for_account",
    "registered_channel_types",
]
