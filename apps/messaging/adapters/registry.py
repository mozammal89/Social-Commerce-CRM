"""
Adapter registry — maps ``channel_type`` to adapter classes.

Usage in a platform adapter module::

    from apps.messaging.adapters.base import BaseChannelAdapter
    from apps.messaging.adapters.registry import register

    @register("facebook_messenger")
    class FacebookAdapter(BaseChannelAdapter): ...

The service layer resolves an adapter dynamically::

    from apps.messaging.adapters.registry import get_adapter
    adapter = get_adapter(connected_account.channel.channel_type)

Adapters self-register on import. ``MessagingConfig.ready()`` imports the
adapters package, so registration happens at startup. Adapters that fail
to import (e.g. a missing optional dependency) log a warning and are
skipped — the rest of the system keeps working.
"""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING

from .base import BaseChannelAdapter

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from ..models import ConnectedAccount

logger = logging.getLogger(__name__)


# channel_type -> adapter class
_ADAPTERS: dict[str, type[BaseChannelAdapter]] = {}


def register(channel_type: str):
    """Class decorator registering an adapter under ``channel_type``.

    Raises ``ValueError`` if a different class is already registered for
    the same type — that signals a real wiring bug rather than silently
    shadowing an adapter.
    """

    def decorator(cls: type[BaseChannelAdapter]) -> type[BaseChannelAdapter]:
        if not issubclass(cls, BaseChannelAdapter):
            raise TypeError(
                f"{cls.__name__} must subclass BaseChannelAdapter to be registered."
            )
        existing = _ADAPTERS.get(channel_type)
        if existing is not None and existing is not cls:
            raise ValueError(
                f"Channel type '{channel_type}' is already registered to "
                f"{existing.__name__}; cannot re-register to {cls.__name__}."
            )
        cls.channel_type = channel_type
        _ADAPTERS[channel_type] = cls
        logger.debug("Registered messaging adapter: %s -> %s", channel_type, cls.__name__)
        return cls

    return decorator


def get_adapter_class(channel_type: str) -> type[BaseChannelAdapter] | None:
    """Return the registered adapter class for a channel type, or None."""
    return _ADAPTERS.get(channel_type)


def get_adapter(channel_type: str) -> BaseChannelAdapter:
    """Instantiate and return the adapter for ``channel_type``.

    Raises ``KeyError`` if no adapter is registered. Callers usually
    resolve via the ``Channel``/``ConnectedAccount`` channel_type.
    """
    cls = _ADAPTERS.get(channel_type)
    if cls is None:
        raise KeyError(
            f"No messaging adapter registered for channel type '{channel_type}'. "
            f"Registered: {sorted(_ADAPTERS)}"
        )
    return cls()


def get_adapter_for_account(account: "ConnectedAccount") -> BaseChannelAdapter:
    """Convenience: adapter for a connected account's channel."""
    return get_adapter(account.channel.channel_type)


def registered_channel_types() -> list[str]:
    """Return all registered channel types (for diagnostics/admin)."""
    return sorted(_ADAPTERS)


def _import_adapters() -> None:
    """Eagerly import every bundled adapter subpackage so they register.

    Each entry is a dotted path to a subpackage containing an
    ``adapter`` module. Failures are logged and skipped so a missing
    optional dependency (e.g. a future SDK) never breaks startup.
    Called from ``MessagingConfig.ready()`` and from the package
    ``__init__`` so importing the adapters package is enough.
    """
    adapter_packages = [
        "apps.messaging.adapters.facebook",
        "apps.messaging.adapters.whatsapp",
    ]
    for dotted in adapter_packages:
        try:
            importlib.import_module(f"{dotted}.adapter")
        except ImportError as exc:
            # Optional adapter not installed yet — skip gracefully.
            logger.warning("Skipping messaging adapter %s: %s", dotted, exc)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Failed to load messaging adapter %s: %s", dotted, exc)
