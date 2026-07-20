"""
Service layer for the omnichannel messaging system.

This is the single place where messaging business logic lives. Views,
webhook handlers and (later) WebSocket consumers call these functions
and never mutate the ORM directly — mirroring the convention in
``apps.permissions.ui.services`` and ``apps.subscriptions.services``.

Layering
--------
::

    Webhook / REST / WebSocket
        └── services  (this module)
              ├── adapters  (platform specifics)
              └── models    (persistence)

Services receive/return normalized DTOs and model instances; they never
see platform JSON. Each mutation runs inside ``transaction.atomic()`` and
records an ``Activity`` row (the messaging timeline / audit trail).

The four services are split by concern:
* ``CustomerService``      — find/create/merge unified profiles
* ``ConversationService``  — threads, assignment, status, inbox listing
* ``MessageService``       — ingest inbound, send outbound, delivery status
* ``ChannelService``       — connect/enable/disable channel accounts

Realtime broadcast + notifications are invoked via ``_emit_*`` hooks at
the bottom of the file. They are no-ops today (Phase 1/2) and will be
implemented in the realtime phase (Channels + Celery) without touching
the service signatures.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.stores.models import Store

from .adapters import (
    DeliveryUpdate,
    NormalizedIncomingEvent,
    OutboundMessage,
    SendResult,
    SendMessageError,
    get_adapter,
    get_adapter_for_account,
)
from .adapters.dto import OutboundAttachment
from .constants import (
    ACTIVE_CONVERSATION_STATUSES,
    ActivityType,
    ConnectedAccountStatus,
    ConversationPriority,
    ConversationStatus,
    DeliveryStatus,
    MessageDirection,
    MessageType,
    SenderType,
)
from .models import (
    Activity,
    Attachment,
    ConnectedAccount,
    Conversation,
    Customer,
    CustomerChannelIdentity,
    CustomerNote,
    CustomerTag,
    InternalNote,
    Message,
)

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    pass

logger = logging.getLogger(__name__)
User = get_user_model()

# Max chars of message body stored in Conversation.last_message_preview.
PREVIEW_LENGTH = 160


def _enqueue_enrichment(identity_id: str) -> None:
    """Fire-and-forget enqueue of profile enrichment for a new identity.

    Imported lazily to break the services↔tasks circular import (tasks.py
    imports services.py for ``MessageService`` etc., so services.py must
    not import tasks.py at module load time). Swallows all errors so
    webhook ingestion never breaks if Celery is down or misconfigured —
    the daily ``sync_customer_profiles`` task is the safety net that
    catches any identity whose ``last_synced_at`` is still NULL.
    """
    try:
        from .tasks import enrich_customer_identity

        enrich_customer_identity.delay(identity_id)
    except Exception:
        logger.exception(
            "Failed to enqueue enrich_customer_identity for %s — the daily sync will retry",
            identity_id,
        )


# ===========================================================================
# Customer service
# ===========================================================================
class CustomerService:
    """Unified customer profile operations."""

    # ------------------------------------------------------------------
    # Find-or-create from a webhook identity
    # ------------------------------------------------------------------
    @staticmethod
    def get_or_create_by_identity(
        *,
        connected_account: ConnectedAccount,
        external_id: str,
        profile: dict[str, Any] | None = None,
    ) -> tuple[Customer, CustomerChannelIdentity, bool]:
        """Resolve a customer from a channel identity, creating if needed.

        Resolution tiers (in order):

        1. **Identity match** — ``(store, channel, external_id)`` unique
           key on CustomerChannelIdentity. Always hits for a returning
           sender; the hot path for every inbound message.

        2. **Cross-channel contact match** — when the inbound payload
           yields a channel-verified email or phone and that contact
           already belongs to an active (un-merged) Customer in the same
           store, attach the new identity to that customer via
           :meth:`CustomerProfileService.link_identity` instead of
           creating a duplicate. Verified-contact rules:
             * WhatsApp — ``external_id`` IS the E.164 phone number.
             * Future email channel — ``external_id`` IS the email.
             * Others — only explicit ``profile['email']`` / ``profile['phone']``.

        3. **Create** — no match: build a new Customer (with verified
           contact info persisted, so future Tier 2 lookups can find it)
           + a new CustomerChannelIdentity.

        Returns ``(customer, identity, created_customer)`` where
        ``created_customer`` is True only at tier 3.
        """
        profile = profile or {}
        channel = connected_account.channel

        with transaction.atomic():
            # --- Tier 1: identity lookup -------------------------------
            identity = (
                CustomerChannelIdentity.objects.select_related("customer")
                .filter(
                    store=connected_account.store,
                    channel=channel,
                    external_id=external_id,
                )
                .first()
            )
            if identity is not None:
                # Enrich display name/avatar if we now know more.
                CustomerService._maybe_enrich_identity(identity, profile)
                return identity.customer, identity, False

            # --- Tier 2: cross-channel contact match ------------------
            email, phone = CustomerService._extract_verified_contact(
                channel_slug=channel.slug,
                external_id=external_id,
                profile=profile,
            )
            existing = CustomerService._find_active_by_contact(
                store=connected_account.store,
                email=email,
                phone=phone,
            )
            if existing is not None:
                # Attach the new identity to the existing customer. This
                # is the duplicate-prevention path: a WA sender whose
                # phone matches an existing customer (e.g. one created
                # earlier via FB + agent-added phone) gets linked rather
                # than duplicated.
                identity, _ident_created = CustomerProfileService.link_identity(
                    customer=existing,
                    connected_account=connected_account,
                    external_id=external_id,
                    profile=profile,
                )
                # Enqueue lazy enrichment for the newly-linked identity
                # (same rule as the create path: skip when webhook had a
                # display_name already).
                webhook_had_name = bool(profile.get("display_name") or profile.get("name"))
                if not webhook_had_name:
                    transaction.on_commit(lambda iid=str(identity.id): _enqueue_enrichment(iid))
                return existing, identity, False

            # --- Tier 3: create new customer + identity ----------------
            display_name = profile.get("display_name") or profile.get("name") or external_id
            customer = Customer.objects.create(
                store=connected_account.store,
                first_name=profile.get("first_name", ""),
                last_name=profile.get("last_name", ""),
                display_name=display_name,
                avatar=profile.get("avatar_url", ""),
                # Persist verified contact so future Tier 2 lookups can
                # find this customer from a different channel.
                email=email or (profile.get("email") or "").strip().lower(),
                phone=phone or (profile.get("phone") or "").strip(),
                first_seen_at=timezone.now(),
                last_seen_at=timezone.now(),
            )
            identity = CustomerChannelIdentity.objects.create(
                store=connected_account.store,
                customer=customer,
                connected_account=connected_account,
                channel=channel,
                external_id=external_id,
                display_name=display_name,
                avatar_url=profile.get("avatar_url", ""),
                metadata=profile.get("extra", {}) or {},
            )
            Activity.objects.create(
                store=connected_account.store,
                customer=customer,
                action_type=ActivityType.CUSTOMER_CREATED.value,
                description=f"Customer created via {channel.name}",
                metadata={"channel": channel.slug, "external_id": external_id},
            )

            # Lazy profile enrichment: ask the channel API for the real
            # name/avatar/locale/timezone. Skipped when the webhook
            # payload already carried a display_name (WhatsApp does this
            # — avoids redundant API work). Scheduled via on_commit so
            # the task never sees a half-committed identity. Failure is
            # non-fatal: the daily sync_store_profiles task catches any
            # identity whose last_synced_at is still NULL.
            webhook_had_name = bool(profile.get("display_name") or profile.get("name"))
            if not webhook_had_name:
                transaction.on_commit(lambda iid=str(identity.id): _enqueue_enrichment(iid))

            return customer, identity, True

    # ------------------------------------------------------------------
    # Cross-channel contact matching (Tier 2 helpers)
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_verified_contact(
        *,
        channel_slug: str,
        external_id: str,
        profile: dict[str, Any],
    ) -> tuple[str, str]:
        """Return ``(email, phone)`` verified by the channel for this sender.

        "Verified" means the channel itself asserts the value — not a
        user-supplied field. The partial unique constraints on
        ``messaging_customer`` (from migration 0003) make these the
        canonical duplicate-prevention keys.

        Channel rules:
          * ``whatsapp`` — ``external_id`` IS the E.164 phone number
            (the Cloud API only accepts real phone numbers as the
            sender; Meta verifies them at delivery). Always trusted.
          * (future) ``email`` — ``external_id`` IS the email address
            (verified at SMTP handshake / DKIM).
          * Others — only explicit ``profile['email']`` / ``profile['phone']``
            keys are trusted; the adapter decides whether to populate
            them from a verified platform field.

        Both values are normalized: email lowercased + trimmed, phone
        stripped of whitespace. Empty string when unavailable.
        """
        email = (profile.get("email") or "").strip().lower()
        phone = (profile.get("phone") or "").strip()
        if channel_slug == "whatsapp" and not phone and external_id:
            # WA sender id is the E.164 phone — verified by the platform.
            phone = external_id.strip()
        return email, phone

    @staticmethod
    def _find_active_by_contact(
        *,
        store,
        email: str,
        phone: str,
    ) -> Customer | None:
        """Find an active (un-merged) customer in ``store`` by verified contact.

        Email wins over phone (a verified email is a stronger signal
        than a phone — numbers get recycled, emails don't). Returns
        ``None`` when both inputs are empty or no match exists.

        The partial unique constraints added in migration 0003
        (``uniq_customer_store_email_active`` and
        ``uniq_customer_store_phone_active``) guarantee at most one
        active customer per (store, contact), so ``.first()`` is
        deterministic — there cannot be two.
        """
        if email:
            match = Customer.objects.filter(store=store, email=email, is_merged=False).first()
            if match is not None:
                return match
        if phone:
            match = Customer.objects.filter(store=store, phone=phone, is_merged=False).first()
            if match is not None:
                return match
        return None

    # ------------------------------------------------------------------
    # Profile enrichment
    # ------------------------------------------------------------------
    @staticmethod
    def _maybe_enrich_identity(identity: CustomerChannelIdentity, profile: dict[str, Any]) -> None:
        """Update an identity/customer with newly-known profile data.

        Only fills in fields that are currently empty — never overwrites
        an agent's manual edits. Saves only when something changed.
        """
        changed = False
        if not identity.display_name and profile.get("display_name"):
            identity.display_name = profile["display_name"]
            changed = True
        if not identity.avatar_url and profile.get("avatar_url"):
            identity.avatar_url = profile["avatar_url"]
            changed = True
        if changed:
            identity.save(update_fields=["display_name", "avatar_url", "updated_at"])

        cust = identity.customer
        cust_changed = False
        if not cust.display_name and profile.get("display_name"):
            cust.display_name = profile["display_name"]
            cust_changed = True
        if not cust.avatar and profile.get("avatar_url"):
            cust.avatar = profile["avatar_url"]
            cust_changed = True
        if not cust.first_name and profile.get("first_name"):
            cust.first_name = profile["first_name"]
            cust_changed = True
        if not cust.last_name and profile.get("last_name"):
            cust.last_name = profile["last_name"]
            cust_changed = True
        if cust_changed:
            cust.last_seen_at = timezone.now()
            cust.save(
                update_fields=[
                    "display_name",
                    "avatar",
                    "first_name",
                    "last_name",
                    "last_seen_at",
                    "updated_at",
                ]
            )
        else:
            # Still bump last_seen — the customer just messaged us.
            Customer.objects.filter(pk=cust.pk).update(last_seen_at=timezone.now())

    @staticmethod
    def update_profile(*, customer: Customer, actor: User | None = None, **fields) -> Customer:
        """Update editable customer fields (called by the CRM UI).

        Marks every touched syncable field as agent-edited so subsequent
        channel profile syncs don't overwrite the agent's changes. The
        source-of-truth record lives on ``Customer.metadata._field_sources``
        and is consulted by ``CustomerProfileService._propagate_to_customer``.
        """
        allowed = {"first_name", "last_name", "display_name", "email", "phone", "avatar", "notes"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return customer
        with transaction.atomic():
            for k, v in updates.items():
                setattr(customer, k, v)
            customer.save(update_fields=list(updates) + ["updated_at"])
            # Record agent edits so the next channel sync skips these fields.
            for field in updates:
                CustomerProfileService.mark_field_as_agent_edited(
                    customer=customer,
                    field_name=field,
                )
            Activity.objects.create(
                store=customer.store,
                customer=customer,
                actor=actor,
                action_type=ActivityType.CUSTOMER_UPDATED.value,
                description="Customer profile updated",
                metadata={"fields": sorted(updates)},
            )
        return customer

    # ------------------------------------------------------------------
    # Merge
    # ------------------------------------------------------------------
    @staticmethod
    def merge(*, primary: Customer, duplicate: Customer, actor: User | None = None) -> Customer:
        """Merge ``duplicate`` into ``primary``.

        Re-points every identity, open conversation and message from the
        duplicate to the primary, then marks the duplicate as merged and
        read-only. Idempotent: merging an already-merged customer is a
        no-op. Runs atomically.
        """
        if duplicate.pk == primary.pk:
            return primary
        if duplicate.is_merged:
            # Follow the chain so callers can pass a stale reference.
            return CustomerService.merge(primary=primary, duplicate=duplicate.primary, actor=actor)

        with transaction.atomic():
            # Re-point everything that referenced the duplicate.
            CustomerChannelIdentity.objects.filter(customer=duplicate).update(customer=primary)
            InternalNote.objects.filter(conversation__customer=duplicate).update(
                # notes stay attached to their conversation; nothing to move
            )
            Conversation.objects.filter(customer=duplicate).update(customer=primary)
            Message.objects.filter(customer=duplicate).update(customer=primary)

            # Merge tags (union onto primary).
            primary.tags.add(*duplicate.tags.all())

            # Last-seen / first-seen window expands to cover both.
            times = [t for t in [primary.first_seen_at, duplicate.first_seen_at] if t]
            if times:
                primary.first_seen_at = min(times)
            times = [t for t in [primary.last_seen_at, duplicate.last_seen_at] if t]
            if times:
                primary.last_seen_at = max(times)

            duplicate.is_merged = True
            duplicate.merged_into = primary
            duplicate.merged_at = timezone.now()
            duplicate.save(update_fields=["is_merged", "merged_into", "merged_at", "updated_at"])
            primary.save(update_fields=["first_seen_at", "last_seen_at", "updated_at"])

            Activity.objects.create(
                store=primary.store,
                customer=primary,
                actor=actor,
                action_type=ActivityType.CUSTOMER_MERGED.value,
                description=f"Merged customer {duplicate.pk} into {primary.pk}",
                metadata={"primary_id": str(primary.pk), "duplicate_id": str(duplicate.pk)},
            )
        return primary

    # ------------------------------------------------------------------
    # Tags & notes
    # ------------------------------------------------------------------
    @staticmethod
    def add_tag(*, customer: Customer, tag: CustomerTag, actor: User | None = None) -> None:
        with transaction.atomic():
            customer.tags.add(tag)
            Activity.objects.create(
                store=customer.store,
                customer=customer,
                actor=actor,
                action_type=ActivityType.TAG_ADDED.value,
                description=f"Tag '{tag.name}' added",
                metadata={"tag_id": str(tag.pk)},
            )

    @staticmethod
    def remove_tag(*, customer: Customer, tag: CustomerTag, actor: User | None = None) -> None:
        with transaction.atomic():
            customer.tags.remove(tag)
            Activity.objects.create(
                store=customer.store,
                customer=customer,
                actor=actor,
                action_type=ActivityType.TAG_REMOVED.value,
                description=f"Tag '{tag.name}' removed",
                metadata={"tag_id": str(tag.pk)},
            )

    @staticmethod
    def add_note(*, customer: Customer, author: User, body: str) -> CustomerNote:
        with transaction.atomic():
            note = CustomerNote.objects.create(customer=customer, author=author, body=body)
            Activity.objects.create(
                store=customer.store,
                customer=customer,
                actor=author,
                action_type=ActivityType.NOTE_ADDED.value,
                description="Customer note added",
                metadata={"note_id": str(note.pk)},
            )
        return note

    # ------------------------------------------------------------------
    # Unified timeline
    # ------------------------------------------------------------------
    @staticmethod
    def timeline(customer: Customer) -> list[dict[str, Any]]:
        """Return a unified, time-ordered timeline for a customer.

        Unions messages, customer notes and activities. Each item is a
        dict ``{type, timestamp, data}`` so the UI can render a single
        stream. Orders plugs in here in a later phase (when the orders
        app exists) by appending items with ``type="order"``.
        """
        items: list[dict[str, Any]] = []
        for msg in customer.messages.select_related("sender").order_by("created_at"):
            items.append(
                {
                    "type": "message",
                    "timestamp": msg.created_at,
                    "data": {
                        "id": str(msg.id),
                        "direction": msg.direction,
                        "message_type": msg.message_type,
                        "text": msg.text,
                        "sender_type": msg.sender_type,
                    },
                }
            )
        for note in customer.customer_notes.select_related("author").order_by("created_at"):
            items.append(
                {
                    "type": "note",
                    "timestamp": note.created_at,
                    "data": {
                        "id": str(note.id),
                        "body": note.body,
                        "author": str(note.author) if note.author else "",
                    },
                }
            )
        for act in customer.activities.order_by("created_at"):
            items.append(
                {
                    "type": "activity",
                    "timestamp": act.created_at,
                    "data": {
                        "id": str(act.id),
                        "action_type": act.action_type,
                        "description": act.description,
                    },
                }
            )
        items.sort(key=lambda i: i["timestamp"] or datetime.min.replace(tzinfo=timezone.utc))
        return items


# ===========================================================================
# Customer profile service — channel-driven enrichment & identity linking
# ===========================================================================
class CustomerProfileService:
    """Channel-driven customer profile enrichment, sync and identity linking.

    This service is the **sole consumer** of
    ``BaseChannelAdapter.fetch_identity_profile()``. It owns:

    * The source-of-truth rule (agent edits vs channel-provided data).
    * Identity refresh lifecycle (``last_synced_at``).
    * Cross-channel identity linking (Tier 2 matching entry point).
    * Duplicate suggestion (Tier 3 heuristic).

    Source-of-truth tracking
    ------------------------
    Every syncable field records who last wrote it:

    * ``CustomerChannelIdentity.profile_metadata["_sources"][field]`` —
      one of ``"channel:<slug>"`` or ``"agent"``. Covers the identity-level
      fields (``display_name``, ``avatar_url``, ``language``, ``timezone``).
    * ``Customer.metadata["_field_sources"][field]`` — same vocabulary,
      covers customer-level fields (``first_name``, ``last_name``,
      ``display_name``, ``avatar``).

    Sync rule for each field:
      1. If the recorded source is ``"agent"`` → never overwrite.
      2. Else if the adapter returned a non-empty value → overwrite and
         record ``"channel:<slug>"``.
      3. Else (adapter returned empty) → leave the existing value intact
         (a transient API miss must not blank stored data).

    An agent can undo their edit (flip the source back to ``"channel"``)
    via :meth:`unmark_agent_edit`, future UI affordance.
    """

    # Fields that live on CustomerChannelIdentity and come from the channel.
    IDENTITY_SYNC_FIELDS: tuple[str, ...] = (
        "display_name",
        "avatar_url",
        "language",
        "timezone",
    )
    # Fields that live on Customer and are propagated from the primary
    # identity. Maps customer field → the key the adapter returns.
    CUSTOMER_SYNC_FIELDS: tuple[str, ...] = (
        "first_name",
        "last_name",
        "display_name",
        "avatar",
    )
    _CUSTOMER_FROM_ADAPTER = {
        "first_name": "first_name",
        "last_name": "last_name",
        "display_name": "display_name",
        "avatar": "avatar_url",
    }
    # Sync window for the periodic batch task.
    SYNC_RESCAN_WINDOW_DAYS = 7

    # ------------------------------------------------------------------
    # Single-identity enrichment (the Celery task target)
    # ------------------------------------------------------------------
    @staticmethod
    def enrich_identity(identity_id) -> bool:
        """Fetch a fresh profile from the channel and update the identity.

        Idempotent and safe to retry. Returns ``True`` when an update was
        applied, ``False`` when the identity was skipped (merged customer,
        unknown identity, or adapter returned nothing new). Never raises
        on adapter failures — logs and returns ``False`` so the Celery
        task doesn't poison the batch.

        Called from:
          * The lazy-enrichment hook in ``CustomerService.get_or_create_by_identity``
            (Step 4) — ``enrich_customer_identity.delay(identity_id)``.
          * The daily ``sync_customer_profiles`` beat task for stale identities.
          * The on-demand ``POST /customers/{id}/identities/{iid}/refresh/``.
        """
        try:
            identity = CustomerChannelIdentity.objects.select_related(
                "customer", "connected_account", "channel"
            ).get(pk=identity_id)
        except CustomerChannelIdentity.DoesNotExist:
            logger.warning("enrich_identity: identity %s not found", identity_id)
            return False

        # Skip merged duplicates — their profile is frozen for history.
        if identity.customer.is_merged:
            return False

        adapter = get_adapter_for_account(identity.connected_account)
        try:
            profile = (
                adapter.fetch_identity_profile(
                    account=identity.connected_account,
                    external_id=identity.external_id,
                )
                or {}
            )
        except Exception:
            logger.exception(
                "enrich_identity: adapter %s raised for identity %s",
                identity.channel.slug,
                identity.id,
            )
            return False

        channel_source = f"channel:{identity.channel.slug}"
        identity_changed = CustomerProfileService._apply_profile_to_identity(
            identity=identity,
            profile=profile,
            channel_source=channel_source,
        )

        # Always record last_synced_at + raw payload, even if nothing else
        # changed — this is what the periodic batch uses to skip fresh rows.
        identity.last_synced_at = timezone.now()
        pmeta = dict(identity.profile_metadata or {})
        pmeta["_raw"] = profile
        identity.profile_metadata = pmeta
        identity.save(
            update_fields=[
                *CustomerProfileService.IDENTITY_SYNC_FIELDS,
                "profile_metadata",
                "last_synced_at",
                "updated_at",
            ]
        )

        # Propagate to the customer profile if this identity is the primary
        # one (or there is no primary yet — first sync auto-promotes).
        customer_changed = False
        if (
            identity.is_primary
            or not identity.customer.channel_identities.filter(is_primary=True).exists()
        ):
            if not identity.is_primary:
                CustomerProfileService.set_primary(identity)
            customer_changed = CustomerProfileService._propagate_to_customer(
                identity=identity,
                profile=profile,
                channel_source=channel_source,
            )

        Activity.objects.create(
            store=identity.store,
            customer=identity.customer,
            action_type=ActivityType.CUSTOMER_PROFILE_SYNCED.value,
            description=f"Profile synced from {identity.channel.name}",
            metadata={
                "identity_id": str(identity.id),
                "channel": identity.channel.slug,
                "identity_changed": identity_changed,
                "customer_changed": customer_changed,
            },
        )
        return True

    # ------------------------------------------------------------------
    # Source-of-truth helpers (internal)
    # ------------------------------------------------------------------
    @staticmethod
    def _apply_profile_to_identity(
        *,
        identity: CustomerChannelIdentity,
        profile: dict[str, Any],
        channel_source: str,
    ) -> bool:
        """Write the adapter profile into the identity's syncable fields.

        Honors the source-of-truth rule: never overwrites an agent-edited
        field. Returns ``True`` if at least one field actually changed.
        Mutates ``identity`` in place but does NOT save it (caller saves).
        """
        pmeta = dict(identity.profile_metadata or {})
        sources = dict(pmeta.get("_sources", {}))
        changed = False
        for field in CustomerProfileService.IDENTITY_SYNC_FIELDS:
            if sources.get(field) == "agent":
                continue
            new_val = profile.get(field, "") or ""
            if new_val and new_val != getattr(identity, field):
                setattr(identity, field, new_val)
                sources[field] = channel_source
                changed = True
        pmeta["_sources"] = sources
        identity.profile_metadata = pmeta
        return changed

    @staticmethod
    def _propagate_to_customer(
        *,
        identity: CustomerChannelIdentity,
        profile: dict[str, Any],
        channel_source: str,
    ) -> bool:
        """Propagate the (primary) identity's profile to its Customer.

        Subject to the source-of-truth rule. Only non-empty adapter values
        overwrite. Returns ``True`` if any customer field was changed.
        """
        customer = identity.customer
        cmeta = dict(customer.metadata or {})
        field_sources = dict(cmeta.get("_field_sources", {}))
        changed = False
        for cust_field, adapter_key in CustomerProfileService._CUSTOMER_FROM_ADAPTER.items():
            if field_sources.get(cust_field) == "agent":
                continue
            new_val = profile.get(adapter_key, "") or ""
            if new_val and new_val != getattr(customer, cust_field):
                setattr(customer, cust_field, new_val)
                field_sources[cust_field] = channel_source
                changed = True
        if changed:
            cmeta["_field_sources"] = field_sources
            customer.metadata = cmeta
            customer.last_seen_at = timezone.now()
            customer.save(
                update_fields=[
                    *CustomerProfileService.CUSTOMER_SYNC_FIELDS,
                    "metadata",
                    "last_seen_at",
                    "updated_at",
                ]
            )
        return changed

    @staticmethod
    def set_primary(identity: CustomerChannelIdentity) -> CustomerChannelIdentity:
        """Mark ``identity`` as the primary for its customer; unsets siblings.

        The primary identity is the one whose profile propagates to the
        Customer card. Enforced at the service layer (not the DB) so we
        don't need a partial unique constraint that complicates migrations.
        """
        with transaction.atomic():
            (
                CustomerChannelIdentity.objects.filter(customer=identity.customer, is_primary=True)
                .exclude(pk=identity.pk)
                .update(is_primary=False)
            )
            if not identity.is_primary:
                identity.is_primary = True
                identity.save(update_fields=["is_primary", "updated_at"])
        return identity

    @staticmethod
    def mark_field_as_agent_edited(
        *,
        customer: Customer,
        field_name: str,
    ) -> None:
        """Record that ``field_name`` on ``customer`` was agent-edited.

        After this, channel sync will not overwrite that field until
        :meth:`unmark_agent_edit` flips it back. Called by
        ``CustomerService.update_profile`` for every field the agent touched.
        Safe to call for fields not in ``CUSTOMER_SYNC_FIELDS`` (no-op).
        """
        if field_name not in CustomerProfileService.CUSTOMER_SYNC_FIELDS:
            return
        cmeta = dict(customer.metadata or {})
        field_sources = dict(cmeta.get("_field_sources", {}))
        field_sources[field_name] = "agent"
        cmeta["_field_sources"] = field_sources
        customer.metadata = cmeta
        customer.save(update_fields=["metadata", "updated_at"])

    @staticmethod
    def unmark_agent_edit(*, customer: Customer, field_name: str) -> None:
        """Allow channel sync to overwrite ``field_name`` again.

        Future UI affordance ("Undo agent edit"). The next sync of the
        primary identity will repopulate the field.
        """
        cmeta = dict(customer.metadata or {})
        field_sources = dict(cmeta.get("_field_sources", {}))
        field_sources.pop(field_name, None)
        cmeta["_field_sources"] = field_sources
        customer.metadata = cmeta
        customer.save(update_fields=["metadata", "updated_at"])

    # ------------------------------------------------------------------
    # Cross-channel identity linking (Tier 2 entry point)
    # ------------------------------------------------------------------
    @staticmethod
    def link_identity(
        *,
        customer: Customer,
        connected_account: ConnectedAccount,
        external_id: str,
        profile: dict[str, Any] | None = None,
    ) -> tuple[CustomerChannelIdentity, bool]:
        """Attach a new channel identity to an existing customer.

        This is the Tier 2 cross-channel matching path: when an inbound
        payload yields a verified email/phone that matches an existing
        Customer, the service layer calls this to attach the new identity
        to that customer instead of creating a duplicate.

        Returns ``(identity, created)``. Idempotent: if the identity
        already exists it is returned unchanged (with ``created=False``).
        The customer must belong to the same store as the account.
        """
        profile = profile or {}
        channel = connected_account.channel
        if customer.store_id != connected_account.store_id:
            raise ValueError(
                "link_identity: customer and connected_account must belong to the same store."
            )

        with transaction.atomic():
            identity, created = CustomerChannelIdentity.objects.get_or_create(
                store=connected_account.store,
                channel=channel,
                external_id=external_id,
                defaults={
                    "customer": customer,
                    "connected_account": connected_account,
                    "display_name": profile.get("display_name", ""),
                    "avatar_url": profile.get("avatar_url", ""),
                    "language": profile.get("language", ""),
                    "timezone": profile.get("timezone", ""),
                    "metadata": profile.get("extra", {}) or {},
                },
            )
            if not created:
                return identity, False

            # Auto-promote to primary if this is the customer's first identity.
            if not customer.channel_identities.filter(is_primary=True).exists():
                identity.is_primary = True
                identity.save(update_fields=["is_primary", "updated_at"])

            Activity.objects.create(
                store=connected_account.store,
                customer=customer,
                action_type=ActivityType.CUSTOMER_IDENTITY_LINKED.value,
                description=f"Linked {channel.name} identity to existing customer",
                metadata={
                    "identity_id": str(identity.id),
                    "channel": channel.slug,
                    "external_id": external_id,
                },
            )
            return identity, created

    # ------------------------------------------------------------------
    # Batch sync (the daily beat target)
    # ------------------------------------------------------------------
    @staticmethod
    def sync_store_profiles(*, store_id, batch_size: int = 500) -> dict[str, int]:
        """Refresh all stale identities for one store.

        Stale = ``last_synced_at`` older than :attr:`SYNC_RESCAN_WINDOW_DAYS`
        or NULL (never synced). Runs in batches to bound memory; per-row
        failures are logged but don't abort the batch. Designed to be
        called from a Celery task — not the request path.

        Returns ``{checked, refreshed, skipped, failed}`` for monitoring.
        """
        cutoff = timezone.now() - timedelta(
            days=CustomerProfileService.SYNC_RESCAN_WINDOW_DAYS,
        )
        qs = (
            CustomerChannelIdentity.objects.filter(store_id=store_id)
            .exclude(customer__is_merged=True)
            .filter(Q(last_synced_at__isnull=True) | Q(last_synced_at__lt=cutoff))
            .values_list("pk", flat=True)
            .order_by("last_synced_at")
        )
        summary = {"checked": 0, "refreshed": 0, "skipped": 0, "failed": 0}
        pks = list(qs[:batch_size])
        for pk in pks:
            summary["checked"] += 1
            try:
                ok = CustomerProfileService.enrich_identity(pk)
            except Exception:
                logger.exception("sync_store_profiles: identity %s raised", pk)
                summary["failed"] += 1
            else:
                if ok:
                    summary["refreshed"] += 1
                else:
                    summary["skipped"] += 1
        logger.info("sync_store_profiles(%s): %s", store_id, summary)
        return summary

    # ------------------------------------------------------------------
    # Tier 3 duplicate suggestion (heuristic, never auto-merges)
    # ------------------------------------------------------------------
    @staticmethod
    def detect_duplicates(*, store_id, limit: int = 50) -> list[dict[str, Any]]:
        """Return likely-duplicate customer pairs for manual review.

        Heuristic, never auto-merges. Looks for active (un-merged)
        customers in the same store sharing strong signals:

          * identical avatar URL (often the same person across channels)
          * identical normalized display name AND overlapping recency

        Each suggestion is ``{primary_id, duplicate_id, reason, score,
        primary_name, duplicate_name}`` ready for UI review. ``score`` is
        0..1 (higher = stronger match). Capped at ``limit`` results.

        Note: email/phone duplicates are already prevented by the partial
        unique constraints from migration 0003, so we don't scan for them
        here — those would be a data integrity bug, not a suggestion.
        """
        active = list(
            Customer.objects.filter(store_id=store_id, is_merged=False)
            .values("id", "display_name", "first_name", "last_name", "avatar", "last_seen_at")
            .order_by("-last_seen_at")[:500]
        )
        suggestions: list[dict[str, Any]] = []

        # Signal 1: identical avatar URL. (Empty avatars are common, so
        # they're filtered INSIDE this block — not at the query level —
        # so avatar-less customers can still match on name.)
        by_avatar: dict[str, list[dict]] = {}
        for c in active:
            avatar = (c["avatar"] or "").strip()
            if avatar:
                by_avatar.setdefault(avatar, []).append(c)
        for avatar, group in by_avatar.items():
            if len(group) < 2:
                continue
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    suggestions.append(
                        {
                            "primary_id": str(group[i]["id"]),
                            "duplicate_id": str(group[j]["id"]),
                            "primary_name": group[i]["display_name"]
                            or f"{group[i]['first_name']} {group[i]['last_name']}".strip(),
                            "duplicate_name": group[j]["display_name"]
                            or f"{group[j]['first_name']} {group[j]['last_name']}".strip(),
                            "reason": "identical_avatar",
                            "score": 0.9,
                            "evidence": {"avatar": avatar[:80]},
                        }
                    )

        # Signal 2: identical normalized display name + recency overlap (<=7d).
        def _norm(name: str) -> str:
            return "".join(c.lower() for c in (name or "") if c.isalnum())

        by_name: dict[str, list[dict]] = {}
        for c in active:
            n = _norm(c["display_name"] or f"{c['first_name']}{c['last_name']}")
            if len(n) >= 4:  # skip very short / generic names
                by_name.setdefault(n, []).append(c)
        now = timezone.now()
        for n, group in by_name.items():
            if len(group) < 2:
                continue
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    a, b = group[i], group[j]
                    ta = a["last_seen_at"] or now
                    tb = b["last_seen_at"] or now
                    days_apart = abs((ta - tb).total_seconds()) / 86400
                    if days_apart <= 7:
                        suggestions.append(
                            {
                                "primary_id": str(a["id"]),
                                "duplicate_id": str(b["id"]),
                                "primary_name": a["display_name"],
                                "duplicate_name": b["display_name"],
                                "reason": "same_name_recent",
                                "score": 0.6,
                                "evidence": {"name": n, "days_apart": round(days_apart, 1)},
                            }
                        )

        suggestions.sort(key=lambda s: s["score"], reverse=True)
        # De-duplicate by (primary_id, duplicate_id) keeping the strongest.
        seen: set[tuple[str, str]] = set()
        out: list[dict[str, Any]] = []
        for s in suggestions:
            key = tuple(sorted([s["primary_id"], s["duplicate_id"]]))
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
            if len(out) >= limit:
                break
        return out


# ===========================================================================
# Conversation service
# ===========================================================================
class ConversationService:
    """Conversation lifecycle & inbox queries."""

    # ------------------------------------------------------------------
    # Find-or-create for an inbound message
    # ------------------------------------------------------------------
    @staticmethod
    def get_or_create_for_inbound(
        *,
        connected_account: ConnectedAccount,
        customer: Customer,
    ) -> tuple[Conversation, bool]:
        """Get the active conversation for (account, customer), else create.

        Honors the partial unique constraint: only one OPEN/PENDING
        conversation per (account, customer) exists; resolved/closed ones
        don't count. Returns ``(conversation, created)``.
        """
        channel = connected_account.channel
        with transaction.atomic():
            conv = Conversation.objects.filter(
                store=connected_account.store,
                connected_account=connected_account,
                customer=customer,
                status__in=ACTIVE_CONVERSATION_STATUSES,
            ).first()
            if conv is not None:
                return conv, False

            conv = Conversation.objects.create(
                store=connected_account.store,
                connected_account=connected_account,
                channel=channel,
                customer=customer,
                status=ConversationStatus.OPEN.value,
            )
            Activity.objects.create(
                store=conv.store,
                conversation=conv,
                customer=customer,
                action_type=ActivityType.CONVERSATION_CREATED.value,
                description=f"New conversation on {channel.name}",
            )
            return conv, True

    # ------------------------------------------------------------------
    # Mutation operations
    # ------------------------------------------------------------------
    @staticmethod
    def assign(
        *, conversation: Conversation, agent: User | None, actor: User | None = None
    ) -> Conversation:
        with transaction.atomic():
            previous = conversation.assigned_to_id
            conversation.assigned_to = agent
            conversation.save(update_fields=["assigned_to", "updated_at"])
            action = (
                ActivityType.CONVERSATION_ASSIGNED.value
                if agent
                else ActivityType.CONVERSATION_UNASSIGNED.value
            )
            Activity.objects.create(
                store=conversation.store,
                conversation=conversation,
                customer=conversation.customer,
                actor=actor,
                action_type=action,
                description=f"Assigned to {agent.get_full_name() or agent.email}"
                if agent
                else "Unassigned",
                metadata={
                    "agent_id": str(agent.pk) if agent else None,
                    "previous_id": str(previous) if previous else None,
                },
            )
        _emit_conversation_updated(conversation)
        return conversation

    @staticmethod
    def set_status(
        *, conversation: Conversation, status: str, actor: User | None = None
    ) -> Conversation:
        with transaction.atomic():
            previous = conversation.status
            conversation.status = status
            update_fields = ["status", "updated_at"]
            if status in (ConversationStatus.CLOSED.value, ConversationStatus.RESOLVED.value):
                conversation.closed_at = timezone.now()
                conversation.closed_by = actor
                update_fields += ["closed_at", "closed_by"]
            elif status in ACTIVE_CONVERSATION_STATUSES:
                # Re-opening clears the closed metadata.
                conversation.closed_at = None
                conversation.closed_by = None
                update_fields += ["closed_at", "closed_by"]
            conversation.save(update_fields=update_fields)
            Activity.objects.create(
                store=conversation.store,
                conversation=conversation,
                customer=conversation.customer,
                actor=actor,
                action_type=ActivityType.CONVERSATION_STATUS_CHANGED.value,
                description=f"Status {previous} -> {status}",
                metadata={"previous": previous, "status": status},
            )
        _emit_conversation_updated(conversation)
        return conversation

    @staticmethod
    def set_priority(
        *, conversation: Conversation, priority: str, actor: User | None = None
    ) -> Conversation:
        with transaction.atomic():
            previous = conversation.priority
            conversation.priority = priority
            conversation.save(update_fields=["priority", "updated_at"])
            Activity.objects.create(
                store=conversation.store,
                conversation=conversation,
                customer=conversation.customer,
                actor=actor,
                action_type=ActivityType.CONVERSATION_PRIORITY_CHANGED.value,
                description=f"Priority {previous} -> {priority}",
                metadata={"previous": previous, "priority": priority},
            )
        _emit_conversation_updated(conversation)
        return conversation

    @staticmethod
    def mark_read(*, conversation: Conversation) -> Conversation:
        """Reset unread count (called when an agent opens the conversation)."""
        if conversation.unread_count == 0:
            return conversation
        with transaction.atomic():
            conversation.unread_count = 0
            conversation.save(update_fields=["unread_count", "updated_at"])
        _emit_conversation_updated(conversation)
        return conversation

    @staticmethod
    def add_internal_note(
        *, conversation: Conversation, author: User, body: str, mentions=None
    ) -> InternalNote:
        with transaction.atomic():
            note = InternalNote.objects.create(
                store=conversation.store,
                conversation=conversation,
                author=author,
                body=body,
            )
            if mentions:
                note.mentions.set(mentions)
            Activity.objects.create(
                store=conversation.store,
                conversation=conversation,
                customer=conversation.customer,
                actor=author,
                action_type=ActivityType.NOTE_ADDED.value,
                description="Internal note added",
                metadata={"note_id": str(note.pk)},
            )
        _emit_conversation_updated(conversation)
        return note

    # ------------------------------------------------------------------
    # Inbox queries
    # ------------------------------------------------------------------
    @staticmethod
    def list_for_inbox(
        *,
        store: Store,
        status: str | None = None,
        channel_id: str | None = None,
        assigned_to: str | None = None,
        unassigned_only: bool = False,
    ) -> QuerySet[Conversation]:
        """Return conversations for the unified inbox, newest first.

        ``assigned_to`` accepts a user id OR the literal ``"me"`` (maps
        to the current user in the view layer). ``unassigned_only``
        returns only conversations with no agent.
        """
        qs = Conversation.objects.filter(store=store, is_deleted=False).select_related(
            "customer", "channel", "connected_account", "assigned_to"
        )
        if status:
            qs = qs.filter(status=status)
        if channel_id:
            qs = qs.filter(channel_id=channel_id)
        if unassigned_only:
            qs = qs.filter(assigned_to__isnull=True)
        elif assigned_to:
            qs = qs.filter(assigned_to_id=assigned_to)
        return qs.order_by("-last_message_at", "-created_at")

    @staticmethod
    def search(*, store: Store, query: str) -> QuerySet[Conversation]:
        """Full-text-ish search across message text, customer name, subject."""
        qs = Conversation.objects.filter(store=store, is_deleted=False).distinct()
        return (
            qs.filter(
                Q(subject__icontains=query)
                | Q(customer__display_name__icontains=query)
                | Q(customer__first_name__icontains=query)
                | Q(customer__last_name__icontains=query)
                | Q(messages__text__icontains=query)
            )
            .select_related("customer", "channel")
            .order_by("-last_message_at")
        )


# ===========================================================================
# Message service
# ===========================================================================
class MessageService:
    """Inbound ingestion, outbound sending, delivery tracking."""

    # ------------------------------------------------------------------
    # Inbound (from webhook, via adapter)
    # ------------------------------------------------------------------
    @staticmethod
    def ingest_normalized(
        *,
        connected_account: ConnectedAccount,
        event: NormalizedIncomingEvent,
    ) -> Message | None:
        """Persist one normalized inbound event. Idempotent on external_id.

        This is the core of the webhook flow:
          1. find-or-create customer from the sender identity
          2. (optionally) enrich the profile via the adapter
          3. find-or-create the active conversation
          4. dedupe on (connected_account, external_id)
          5. create the message + attachments
          6. bump conversation denormalized fields & emit activity
          7. trigger realtime + notification hooks
        Returns the Message, or None if it was a duplicate (already stored).
        """
        if not event.external_message_id:
            logger.warning("Inbound event without external_message_id; skipping: %s", event.raw)
            return None

        with transaction.atomic():
            # 1+2. Customer resolution + best-effort profile enrichment.
            customer, _identity, _created = CustomerService.get_or_create_by_identity(
                connected_account=connected_account,
                external_id=event.sender_external_id,
                profile={
                    "display_name": event.sender_display_name,
                    "avatar_url": event.sender_avatar_url,
                    **(event.sender_profile or {}),
                },
            )

            # 3. Conversation resolution.
            conversation, conv_created = ConversationService.get_or_create_for_inbound(
                connected_account=connected_account,
                customer=customer,
            )

            # 4. Idempotency: skip if we've already stored this message.
            already = Message.objects.filter(
                connected_account=connected_account,
                external_id=event.external_message_id,
            ).exists()
            if already:
                return None

            # 5. Persist the message.
            logger.info(
                f"[Webhook] Ingesting message: external_id={event.external_message_id}, attachments_count={len(event.attachments)}"
            )
            print(f"[DEBUG] Ingesting message: attachments_count={len(event.attachments)}")
            if event.attachments:
                for att in event.attachments:
                    logger.info(
                        f"[Webhook] Event attachment: type={att.attachment_type}, url={att.external_url}"
                    )
                    print(
                        f"[DEBUG] Event attachment: type={att.attachment_type}, url={att.external_url}"
                    )
            # Resolve the reply target: if the event references another
            # message by its external id (FB ``reply_to.mid``), link it
            # so the UI can render it as a reply. The referenced message
            # may belong to a different conversation (rare) but must be on
            # the same connected account.
            reply_to_msg = None
            if event.reply_to_external_id:
                reply_to_msg = Message.objects.filter(
                    connected_account=connected_account,
                    external_id=event.reply_to_external_id,
                ).first()
            message = Message.objects.create(
                store=connected_account.store,
                conversation=conversation,
                connected_account=connected_account,
                channel=connected_account.channel,
                external_id=event.external_message_id,
                direction=MessageDirection.INBOUND.value,
                sender_type=SenderType.CUSTOMER.value,
                customer=customer,
                message_type=event.message_type,
                text=event.text,
                quick_replies=event.quick_replies,
                delivery_status=DeliveryStatus.DELIVERED.value,
                external_timestamp=event.external_timestamp,
                delivered_at=timezone.now(),
                reply_to=reply_to_msg,
                raw_payload=event.raw,
                metadata={"location": event.location} if event.location else {},
            )

            # Attachments
            logger.info(
                f"[Webhook] Creating {len(event.attachments)} attachments for message {message.id}"
            )
            print(f"[DEBUG] Creating {len(event.attachments)} attachments for message {message.id}")
            for att in event.attachments:
                logger.info(
                    f"[Webhook] Creating attachment: type={att.attachment_type}, url={att.external_url}"
                )
                print(
                    f"[DEBUG] Creating attachment: type={att.attachment_type}, url={att.external_url}"
                )
                created_att = Attachment.objects.create(
                    store=connected_account.store,
                    message=message,
                    attachment_type=att.attachment_type,
                    external_url=att.external_url,
                    external_id=att.external_id,
                    mime_type=att.mime_type,
                    file_name=att.file_name,
                    file_size=att.file_size,
                    width=att.width,
                    height=att.height,
                    duration=att.duration,
                    thumbnail_url=att.thumbnail_url,
                    metadata=att.extra,
                )
                logger.info(f"[Webhook] Created attachment with ID: {created_att.id}")
                print(f"[DEBUG] Created attachment with ID: {created_att.id}")
                # NOTE: media download is scheduled as a Celery task in
                # the webhook phase (Phase 3) — Facebook/WhatsApp media
                # URLs are fetched via a separate API call and expire.

            # 6. Bump conversation denormalized counters + emit activity.
            ConversationService._apply_inbound_message(conversation, message)

            Activity.objects.create(
                store=connected_account.store,
                conversation=conversation,
                customer=customer,
                action_type=ActivityType.MESSAGE_RECEIVED.value,
                description=f"Message received via {connected_account.channel.name}",
            )

        # 7. Side-effects (outside the transaction for speed).
        # Refresh from DB to ensure attachments are accessible via relationship
        message.refresh_from_db()
        # Log attachment count after refresh
        att_count_after_refresh = Attachment.objects.filter(message_id=message.id).count()
        logger.info(
            f"[Webhook] After refresh: message {message.id} has {att_count_after_refresh} attachments"
        )
        print(
            f"[DEBUG] After refresh: message {message.id} has {att_count_after_refresh} attachments"
        )
        _emit_message_received(message, conversation)
        _emit_conversation_updated(conversation)
        return message

    # ------------------------------------------------------------------
    # Outbound (from CRM reply)
    # ------------------------------------------------------------------
    @staticmethod
    def send(
        *,
        conversation: Conversation,
        sender: User,
        text: str = "",
        message_type: str = MessageType.TEXT.value,
        attachments: list[OutboundAttachment] | None = None,
        template_name: str = "",
        template_language: str = "",
        template_variables: dict[str, Any] | None = None,
        reply_to: Message | None = None,
    ) -> Message:
        """Send a reply from the CRM through the channel's adapter.

        Creates the outbound Message with PENDING status, calls the
        adapter's send API, then updates delivery status from the
        ``SendResult``. Adapter failures mark the message FAILED (with
        the error code/message) rather than raising, so the inbox shows
        the failure inline.
        """
        connected_account = conversation.connected_account
        # Resolve the recipient's channel id from the customer identity
        # for THIS connected account (a customer may have several).
        identity = CustomerChannelIdentity.objects.filter(
            customer=conversation.customer,
            connected_account=connected_account,
        ).first()
        if identity is None:
            raise ValueError(
                f"Customer {conversation.customer_id} has no identity on "
                f"account {connected_account.id}; cannot send."
            )

        outbound = OutboundMessage(
            recipient_external_id=identity.external_id,
            message_type=message_type,
            text=text,
            attachments=attachments or [],
            template_name=template_name,
            template_language=template_language,
            template_variables=template_variables or {},
            reply_to_external_id=reply_to.external_id if reply_to else "",
        )

        with transaction.atomic():
            message = Message.objects.create(
                store=connected_account.store,
                conversation=conversation,
                connected_account=connected_account,
                channel=connected_account.channel,
                external_id="",  # filled in after the platform returns one
                direction=MessageDirection.OUTBOUND.value,
                sender_type=SenderType.AGENT.value,
                sender=sender,
                customer=conversation.customer,
                message_type=message_type,
                text=text,
                delivery_status=DeliveryStatus.PENDING.value,
                sent_at=timezone.now(),
                reply_to=reply_to,
            )
            # Persist attachment metadata (URLs) on the outbound message.
            for att in outbound.attachments:
                Attachment.objects.create(
                    store=connected_account.store,
                    message=message,
                    attachment_type=att.attachment_type,
                    external_url=att.url,
                    file_name=att.file_name,
                    mime_type=att.mime_type,
                )

        # Call the adapter (outside the transaction — network call).
        adapter = get_adapter_for_account(connected_account)
        try:
            result = adapter.send_message(
                account=connected_account,
                recipient_external_id=outbound.recipient_external_id,
                message=outbound,
            )
        except SendMessageError as exc:
            result = SendResult(
                success=False,
                status=DeliveryStatus.FAILED.value,
                error_message=str(exc),
                error_code=exc.code,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Unexpected adapter error sending message %s", message.id)
            result = SendResult(
                success=False,
                status=DeliveryStatus.FAILED.value,
                error_message=str(exc),
            )

        # Apply the send result.
        with transaction.atomic():
            message.external_id = result.external_id or ""
            message.delivery_status = result.status
            if result.success:
                message.sent_at = timezone.now()
            else:
                message.failed_at = timezone.now()
                message.error_code = result.error_code
                message.error_message = result.error_message
            message.save(
                update_fields=[
                    "external_id",
                    "delivery_status",
                    "sent_at",
                    "failed_at",
                    "error_code",
                    "error_message",
                    "updated_at",
                ]
            )

            ConversationService._apply_outbound_message(conversation, message)

            # Truncate error messages to fit the 255 char limit
            error_desc = result.error_message or "Unknown error"
            if len(error_desc) > 200:  # Leave room for "Send failed: " prefix
                error_desc = error_desc[:200] + "..."

            Activity.objects.create(
                store=connected_account.store,
                conversation=conversation,
                customer=conversation.customer,
                actor=sender,
                action_type=(
                    ActivityType.MESSAGE_SENT.value
                    if result.success
                    else ActivityType.MESSAGE_FAILED.value
                ),
                description=("Reply sent" if result.success else f"Send failed: {error_desc}"),
            )

        # Refresh from DB to ensure attachments are accessible via relationship
        message.refresh_from_db()
        _emit_message_received(message, conversation)
        _emit_conversation_updated(conversation)
        return message

    # ------------------------------------------------------------------
    # Delivery status updates (from webhook receipts)
    # ------------------------------------------------------------------
    @staticmethod
    def update_delivery_status(
        *,
        connected_account: ConnectedAccount,
        update: DeliveryUpdate,
    ) -> int:
        """Apply a delivery/read receipt. Returns the count of messages updated."""
        ids = update.external_message_ids or (
            [update.external_message_id] if update.external_message_id else []
        )
        if not ids:
            return 0

        field_map = {
            DeliveryStatus.SENT.value: "sent_at",
            DeliveryStatus.DELIVERED.value: "delivered_at",
            DeliveryStatus.READ.value: "read_at",
        }
        ts = update.timestamp or timezone.now()
        messages = Message.objects.filter(connected_account=connected_account, external_id__in=ids)
        count = messages.update(delivery_status=update.status)
        # Update the relevant timestamp field per-message (the value
        # depends on status, so do it in Python to keep dialect-agnostic).
        ts_field = field_map.get(update.status)
        if ts_field:
            for m in messages:
                setattr(m, ts_field, ts)
                m.save(update_fields=[ts_field, "updated_at"])
        _emit_delivery_updated(connected_account, ids, update.status)
        return count

    # ------------------------------------------------------------------
    # Reactions (from webhook)
    # ------------------------------------------------------------------
    @staticmethod
    def apply_reaction(
        *,
        connected_account: ConnectedAccount,
        event,  # NormalizedReactionEvent
    ) -> bool:
        """Apply a reaction event (react/unreact) to a message.

        Looks up the referenced message by its external id on this account,
        resolves the reactor to a Customer (best-effort), and upserts or
        removes a ``Reaction`` row. Returns True if applied, False if the
        referenced message wasn't found (e.g. it's older than retention).
        Idempotent on ``external_reaction_id``.
        """
        from .models import Reaction

        msg = Message.objects.filter(
            connected_account=connected_account,
            external_id=event.external_message_id,
        ).first()
        if msg is None:
            return False

        # Resolve the reactor to a Customer (best-effort; a reaction may
        # arrive before the sender profile is known).
        customer = None
        if event.reactor_external_id:
            identity = CustomerChannelIdentity.objects.filter(
                connected_account=connected_account,
                external_id=event.reactor_external_id,
            ).first()
            if identity:
                customer = identity.customer

        with transaction.atomic():
            if event.action == "unreact":
                Reaction.objects.filter(
                    message=msg,
                    external_id=event.external_reaction_id,
                ).delete()
            else:
                Reaction.objects.update_or_create(
                    message=msg,
                    external_id=event.external_reaction_id,
                    defaults={
                        "store": connected_account.store,
                        "reactor_type": "customer",
                        "customer": customer,
                        "emoji": event.emoji,
                    },
                )

        # Broadcast the reaction change so the inbox updates live.
        _emit_reaction_updated(
            connected_account, str(msg.id), str(msg.conversation_id), event.action, event.emoji
        )
        return True


# ===========================================================================
# Channel service
# ===========================================================================
class ChannelService:
    """Connected-account lifecycle."""

    @staticmethod
    def connect_account(
        *,
        store: Store,
        channel_slug: str,
        external_id: str,
        name: str,
        credentials: dict[str, Any],
        webhook_verify_token: str = "",
        actor: User | None = None,
        verify: bool = True,
    ) -> ConnectedAccount:
        """Create (or reconnect) a connected account for a channel.

        Delegates credential validation/normalization to the channel's
        adapter, so platform-specific token exchange lives in the adapter.
        When ``verify=True`` (default), it then calls the adapter's
        ``verify_credentials`` to check the credentials against the
        platform live, setting the account status to ``connected`` on
        success or ``error`` (with a message) on failure. Verification
        failure does NOT roll back the connect — the account is saved
        so the user can fix their credentials and re-verify.
        """
        from .models import Channel

        channel = Channel.objects.get(slug=channel_slug)
        adapter = get_adapter(channel.channel_type)

        normalized = adapter.authenticate_account(
            # Build a transient account for the adapter to read defaults from.
            account=_TransientAccount(store=store, channel=channel, external_id=external_id),
            credentials=credentials,
        )

        with transaction.atomic():
            # Persist first as PENDING so the row exists even if verification
            # fails. Verification below flips it to connected/error.
            account, created = ConnectedAccount.objects.update_or_create(
                store=store,
                channel=channel,
                external_id=external_id,
                defaults={
                    "name": name,
                    "credentials": normalized,
                    "webhook_verify_token": webhook_verify_token,
                    "status": ConnectedAccountStatus.PENDING.value,
                    "connected_by": actor,
                    "error_message": "",
                },
            )
            Activity.objects.create(
                store=store,
                actor=actor,
                action_type=ActivityType.CHANNEL_CONNECTED.value,
                description=f"Connected {channel.name}: {name}",
                metadata={
                    "channel": channel.slug,
                    "external_id": external_id,
                    "account_id": str(account.id),
                },
            )

        # Live credential check. The account is already persisted, so a
        # failure here just marks it ``error`` rather than blocking the
        # connect — the user can fix creds and re-verify via the UI.
        if verify:
            ChannelService.verify_account(account=account, actor=actor)
        else:
            account.status = ConnectedAccountStatus.CONNECTED.value
            account.save(update_fields=["status", "updated_at"])
        account.refresh_from_db()
        return account

    @staticmethod
    def verify_account(
        *,
        account: ConnectedAccount,
        actor: User | None = None,
    ) -> ConnectedAccount:
        """Live-check the account's credentials against the platform.

        Calls the adapter's ``verify_credentials`` (a lightweight GET, e.g.
        FB ``GET /me`` / WA ``GET /{phone_number_id}``) and sets the
        account status + error_message from the result. On success the
        platform-confirmed name is recorded in metadata. Returns the
        account (refreshed). Never raises — failures are recorded as
        status=error with the message.
        """
        adapter = get_adapter_for_account(account)
        try:
            result = adapter.verify_credentials(account=account)
        except Exception as exc:  # pragma: no cover - defensive
            result = type(
                "R",
                (),
                {
                    "valid": False,
                    "error_message": str(exc),
                    "error_code": "error",
                    "account_name": "",
                    "external_id": "",
                    "raw": {},
                },
            )()
        with transaction.atomic():
            if result.valid:
                account.status = ConnectedAccountStatus.CONNECTED.value
                account.error_message = ""
                md = dict(account.metadata or {})
                if result.account_name:
                    md["verified_name"] = result.account_name
                if result.external_id:
                    md["verified_external_id"] = result.external_id
                md["verified_at"] = timezone.now().isoformat()
                account.metadata = md
            else:
                account.status = ConnectedAccountStatus.ERROR.value
                account.error_message = result.error_message or "Verification failed"
            account.last_synced_at = timezone.now()
            account.save(
                update_fields=[
                    "status",
                    "error_message",
                    "metadata",
                    "last_synced_at",
                    "updated_at",
                ]
            )
        return account

    @staticmethod
    def set_status(
        *, account: ConnectedAccount, status: str, actor: User | None = None
    ) -> ConnectedAccount:
        """Enable/disable/error an account without dropping credentials."""
        with transaction.atomic():
            previous = account.status
            account.status = status
            if status == ConnectedAccountStatus.CONNECTED.value:
                account.error_message = ""
            account.save(update_fields=["status", "error_message", "updated_at"])
            action = (
                ActivityType.CHANNEL_CONNECTED.value
                if status == ConnectedAccountStatus.CONNECTED.value
                else ActivityType.CHANNEL_DISCONNECTED.value
            )
            Activity.objects.create(
                store=account.store,
                actor=actor,
                action_type=action,
                description=f"Channel {account.channel.name} {previous} -> {status}",
                metadata={"account_id": str(account.id), "previous": previous, "status": status},
            )
        return account

    @staticmethod
    def disconnect(*, account: ConnectedAccount, actor: User | None = None) -> ConnectedAccount:
        return ChannelService.set_status(
            account=account,
            status=ConnectedAccountStatus.DISCONNECTED.value,
            actor=actor,
        )

    # ------------------------------------------------------------------
    # Token lifecycle — refresh & expiry
    # ------------------------------------------------------------------
    @staticmethod
    def refresh_account_tokens(*, account: ConnectedAccount) -> ConnectedAccount:
        """Attempt to refresh the account's expiring credentials.

        Delegates to the adapter's ``refresh_credentials``. On success
        the account is re-verified and an activity entry is logged. If
        the adapter cannot refresh (returns ``False`` — no refresh
        mechanism), the account is left unchanged. If refresh fails
        irreversibly (``AuthenticationError``), the account is marked
        ``expired`` via :meth:`mark_account_expired`.
        """
        adapter = get_adapter_for_account(account)
        try:
            refreshed = adapter.refresh_credentials(account=account)
        except Exception as exc:
            logger.warning("Token refresh failed for account %s: %s", account.id, exc)
            return ChannelService.mark_account_expired(
                account=account,
                reason=f"Token refresh failed: {exc}",
            )
        if not refreshed:
            return account

        Activity.objects.create(
            store=account.store,
            action_type=ActivityType.CHANNEL_TOKEN_REFRESHED.value,
            description=f"Refreshed token for {account.channel.name}: {account.name}",
            metadata={"account_id": str(account.id), "channel": account.channel.slug},
        )
        account.refresh_from_db()
        return account

    @staticmethod
    def mark_account_expired(
        *,
        account: ConnectedAccount,
        reason: str = "",
    ) -> ConnectedAccount:
        """Mark a connected account as ``expired`` and record an activity.

        Called when a token can no longer be refreshed or validated.
        Sets ``status=expired``, stores the reason in ``error_message``,
        and logs a ``channel.token_expired`` activity so the store owner
        is notified to reconnect their Facebook account.
        """
        previous = account.status
        with transaction.atomic():
            account.status = ConnectedAccountStatus.EXPIRED.value
            account.error_message = reason or (
                "The Facebook access token has expired or been revoked. "
                "Please reconnect your Facebook account."
            )
            account.last_synced_at = timezone.now()
            account.save(
                update_fields=[
                    "status",
                    "error_message",
                    "last_synced_at",
                    "updated_at",
                ]
            )
            Activity.objects.create(
                store=account.store,
                action_type=ActivityType.CHANNEL_TOKEN_EXPIRED.value,
                description=(
                    f"{account.channel.name} ({account.name}) token expired — "
                    f"reconnection required."
                ),
                metadata={
                    "account_id": str(account.id),
                    "channel": account.channel.slug,
                    "previous_status": previous,
                    "reason": reason,
                },
            )
        logger.warning(
            "Account %s marked expired (was %s): %s",
            account.id,
            previous,
            reason,
        )
        return account


# ===========================================================================
# Internal helpers — conversation denormalization & realtime hooks
# ===========================================================================
def _preview(text: str) -> str:
    text = (text or "").strip()
    return text[:PREVIEW_LENGTH] + ("…" if len(text) > PREVIEW_LENGTH else "")


# The ConversationService methods below touch denormalized fields. Kept
# as private helpers on the service for cohesion (they're only called
# from within the service layer).
def _apply_inbound_message(conversation: Conversation, message: Message) -> None:
    """Update conversation counters/preview for a new inbound message."""
    conversation.last_message_at = message.created_at
    conversation.last_message_preview = _preview(message.text or message.message_type)
    conversation.last_message_direction = message.direction
    conversation.unread_count = (conversation.unread_count or 0) + 1
    conversation.message_count = (conversation.message_count or 0) + 1
    # Re-open if it was pending/resolved and the customer writes back.
    if conversation.status not in ACTIVE_CONVERSATION_STATUSES:
        conversation.status = ConversationStatus.OPEN.value
    conversation.save(
        update_fields=[
            "last_message_at",
            "last_message_preview",
            "last_message_direction",
            "unread_count",
            "message_count",
            "status",
            "updated_at",
        ]
    )


def _apply_outbound_message(conversation: Conversation, message: Message) -> None:
    """Update conversation counters/preview for a new outbound message."""
    conversation.last_message_at = message.created_at
    conversation.last_message_preview = _preview(message.text or message.message_type)
    conversation.last_message_direction = message.direction
    conversation.message_count = (conversation.message_count or 0) + 1
    conversation.save(
        update_fields=[
            "last_message_at",
            "last_message_preview",
            "last_message_direction",
            "message_count",
            "updated_at",
        ]
    )


# Attach the helpers to ConversationService for namespacing. Defined as
# module functions above for readability, then aliased here.
ConversationService._apply_inbound_message = staticmethod(_apply_inbound_message)  # type: ignore[attr-defined]
ConversationService._apply_outbound_message = staticmethod(_apply_outbound_message)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Realtime / notification hook points.
#
# These broadcast over the Django Channels Redis layer so any connected
# WebSocket client (inbox or per-conversation) receives the event live.
# The service layer runs in a sync context (Django views / Celery tasks),
# so ``async_to_sync`` bridges to the channel layer's async ``group_send``.
#
# Payloads are plain dicts (not DRF-serialized) to keep them lightweight
# and avoid importing serializers here (which would create a circular
# import). The inbox client merges these into its local state.
#
# All broadcasts are best-effort: if the channel layer is unavailable
# (e.g. Redis down), the message is still persisted — realtime is a
# enhancement, never a dependency of correctness.
# ---------------------------------------------------------------------------
def _channel_layer():
    """Lazily fetch the channel layer. Returns None if unavailable."""
    try:
        from channels.layers import get_channel_layer

        return get_channel_layer()
    except Exception:  # pragma: no cover - channels not configured
        return None


def _broadcast(group_name: str, event_type: str, payload: dict) -> None:
    """Send an event to a channel-layer group. Swallows errors so a
    realtime outage never breaks message ingestion."""
    print(f"[DEBUG] Broadcasting to {group_name}, event_type={event_type}")
    print(f"[DEBUG] Broadcast payload: {payload}")
    layer = _channel_layer()
    if layer is None:
        print(f"[DEBUG] Channel layer is None, skipping broadcast")
        return
    try:
        from asgiref.sync import async_to_sync

        async_to_sync(layer.group_send)(
            group_name,
            {"type": event_type, "payload": payload},
        )
        print(f"[DEBUG] Broadcast sent successfully")
    except Exception:  # pragma: no cover - Redis down / serialization
        logger.warning("Realtime broadcast to %s failed", group_name, exc_info=True)
        print(f"[DEBUG] Broadcast failed: {exc_info}")


def _serialize_message_brief(message: Message) -> dict:
    """Minimal message representation for realtime (no FK joins)."""
    logger.info(f"[WebSocket] Serializing message {message.id}, message.pk={message.pk}")
    print(f"[DEBUG] Serializing message {message.id}, message.pk={message.pk}")
    # Include attachments in the payload so images render correctly in real-time
    attachments_data = []
    if message.pk and message.id:  # Only fetch attachments if message is saved
        try:
            # Explicitly query by message_id to avoid Django ORM relationship caching issues
            # Use raw SQL to bypass any potential ORM issues in Celery context
            from django.db import connection

            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM messaging_attachment WHERE message_id = %s", [message.id]
                )
                raw_count = cursor.fetchone()[0]
                print(f"[DEBUG] RAW SQL COUNT: {raw_count} attachments for message {message.id}")

            attachments_qs = Attachment.objects.filter(message_id=message.id)
            count = attachments_qs.count()
            logger.info(f"[WebSocket] Query returned {count} attachments for message {message.id}")
            print(f"[DEBUG] ORM Query returned {count} attachments for message {message.id}")

            # Also try to get the actual attachment objects
            attachments_list = list(attachments_qs)
            print(f"[DEBUG] Materialized {len(attachments_list)} attachment objects")

            for att in attachments_list:
                print(
                    f"[DEBUG] Attachment: id={att.id}, type={att.attachment_type}, url={att.external_url}"
                )
                attachments_data.append(
                    {
                        "id": str(att.id),
                        "attachment_type": att.attachment_type or "",
                        "external_url": att.external_url or "",
                        "mime_type": att.mime_type or "",
                        "file_name": att.file_name or "",
                        "file_size": att.file_size or 0,
                        "width": att.width or 0,
                        "height": att.height or 0,
                        "thumbnail_url": att.thumbnail_url or "",
                    }
                )

            logger.info(
                f"[WebSocket] Serialized {len(attachments_data)} attachments for message {message.id}"
            )
            print(
                f"[DEBUG] Serialized {len(attachments_data)} attachments for message {message.id}"
            )
        except Exception as e:
            logger.warning(f"Failed to fetch attachments for message {message.id}: {e}")
            print(f"[DEBUG] Failed to fetch attachments: {e}")
            import traceback

            traceback.print_exc()

    # Include first attachment of replied-to message for image preview in reply quotes
    reply_to_first_attachment = None
    if message.reply_to_id:
        try:
            # Explicitly query by message_id to avoid Django ORM relationship caching issues
            first_att = Attachment.objects.filter(message_id=message.reply_to_id).first()
            if first_att:
                reply_to_first_attachment = {
                    "id": str(first_att.id),
                    "attachment_type": first_att.attachment_type,
                    "external_url": first_att.external_url,
                    "thumbnail_url": first_att.thumbnail_url,
                    "mime_type": first_att.mime_type,
                }
        except Exception as e:
            logger.warning(f"Failed to fetch reply_to attachment for message {message.id}: {e}")

    payload = {
        "id": str(message.id),
        "conversation_id": str(message.conversation_id),
        "direction": message.direction,
        "sender_type": message.sender_type,
        "message_type": message.message_type,
        "text": message.text or "",
        "delivery_status": message.delivery_status,
        "reply_to_text": message.reply_to.text
        if message.reply_to_id and message.reply_to
        else None,
        "reply_to_message_type": message.reply_to.message_type
        if message.reply_to_id and message.reply_to
        else None,
        "reply_to_has_attachments": Attachment.objects.filter(
            message_id=message.reply_to_id
        ).exists()
        if message.reply_to_id
        else False,
        "reply_to_first_attachment": reply_to_first_attachment,
        "attachments": attachments_data,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }
    logger.info(
        f"[WebSocket] Serialized message {message.id} with {len(attachments_data)} attachments for WebSocket broadcast"
    )
    return payload


def _serialize_conversation_brief(conversation: Conversation) -> dict:
    """Minimal conversation representation for realtime updates."""
    return {
        "id": str(conversation.id),
        "status": conversation.status,
        "priority": conversation.priority,
        "assigned_to_id": str(conversation.assigned_to_id) if conversation.assigned_to_id else None,
        "unread_count": conversation.unread_count,
        "message_count": conversation.message_count,
        "last_message_at": conversation.last_message_at.isoformat()
        if conversation.last_message_at
        else None,
        "last_message_preview": conversation.last_message_preview,
        "last_message_direction": conversation.last_message_direction,
    }


def _emit_message_received(message: Message, conversation: Conversation) -> None:
    """Broadcast a new/updated message to the store inbox + the conversation."""
    payload = _serialize_message_brief(message)
    store_id = str(conversation.store_id)
    conv_id = str(conversation.id)
    # Inbox feed: new message in any conversation.
    _broadcast(f"inbox.{store_id}", "message.new", payload)
    # Per-conversation feed: message in this thread.
    _broadcast(f"conversation.{conv_id}", "message.new", payload)


def _emit_conversation_updated(conversation: Conversation) -> None:
    """Broadcast a conversation metadata change (status, assignment, preview)."""
    payload = _serialize_conversation_brief(conversation)
    _broadcast(f"inbox.{str(conversation.store_id)}", "conversation.updated", payload)


def _emit_delivery_updated(account: ConnectedAccount, message_ids: list[str], status: str) -> None:
    """Broadcast a delivery-status change for a set of messages.

    Delivered to the per-conversation group(s). Since one receipt may
    cover messages across conversations, we look up the conversation ids
    and broadcast per conversation. The inbox group gets a lighter
    ``message.updated`` event too.
    """
    if not message_ids:
        return
    # Resolve conversation ids for the affected messages (one query).
    conv_ids = set(
        Message.objects.filter(connected_account=account, external_id__in=message_ids).values_list(
            "conversation_id", flat=True
        )
    )
    for cid in conv_ids:
        _broadcast(
            f"conversation.{cid}",
            "message.updated",
            {"message_ids": message_ids, "status": status},
        )
    # Inbox-level signal so list items can update their tick marks.
    _broadcast(
        f"inbox.{str(account.store_id)}",
        "message.updated",
        {"message_ids": message_ids, "status": status},
    )


def _emit_reaction_updated(
    account: ConnectedAccount,
    message_id: str,
    conversation_id: str,
    action: str,
    emoji: str,
) -> None:
    """Broadcast a reaction add/remove so the inbox updates live."""
    payload = {
        "message_id": message_id,
        "conversation_id": conversation_id,
        "reaction": action,  # "react" | "unreact"
        "emoji": emoji,
    }
    _broadcast(f"inbox.{str(account.store_id)}", "message.reaction", payload)
    _broadcast(f"conversation.{conversation_id}", "message.reaction", payload)


class _TransientAccount:
    """Minimal stand-in passed to adapters during connect_account.

    Adapters read ``account.store``, ``account.channel`` and
    ``account.external_id`` (plus ``credentials``/``webhook_verify_token``
    via dict access) during ``authenticate_account``. We don't have a
    real ConnectedAccount yet (credentials aren't normalized), so this
    lightweight object provides just what the adapter needs without
    persisting half-formed data.
    """

    def __init__(self, *, store, channel, external_id):
        self.store = store
        self.channel = channel
        self.external_id = external_id
        self.credentials: dict[str, Any] = {}
        self.webhook_verify_token = ""
