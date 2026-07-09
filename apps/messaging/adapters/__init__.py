"""
Channel adapter package.

Concrete adapters (Facebook, WhatsApp, ...) live in subpackages and
register themselves with ``apps/messaging/adapters/registry.py``. The
``MessagingConfig.ready()`` hook imports this package so adapters are
registered on startup.

Phase 1 (this commit) ships the package skeleton so the app imports
cleanly; the base adapter, registry and platform adapters are added in
the subsequent service-layer phase. Importing this package must never
fail when no adapter modules exist yet.
"""

# The registry is imported eagerly so that any adapter module added
# later can rely on ``register`` / ``get_adapter`` being available as
# soon as the app registry is ready.
try:
    from .registry import get_adapter, register  # noqa: F401
except Exception:  # pragma: no cover - registry not yet present in phase 1
    # During early phases the registry module may not exist yet; keep
    # the package importable so AppConfig.ready() is a no-op.
    pass
