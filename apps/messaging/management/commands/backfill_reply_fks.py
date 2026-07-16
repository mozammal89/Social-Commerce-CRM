"""
Backfill ``Message.reply_to`` FKs from stored ``raw_payload``.

When the reply-resolution logic was added to ``ingest_normalized``,
messages already in the DB (ingested before the fix) kept
``reply_to=None`` even though their ``raw_payload`` contains the
referenced message id (e.g. FB ``reply_to.mid``). This command scans
those messages, re-parses the reference out of the raw payload, and
links the FK where the referenced message exists.

Idempotent: only touches messages where ``reply_to`` is currently null
and a resolvable reference is found in the raw payload. Safe to re-run.

Usage::

    python manage.py backfill_reply_fks
    python manage.py backfill_reply_fks --dry-run
"""

import json
import logging

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.messaging.models import Message

logger = logging.getLogger(__name__)


def _extract_reply_to_mid(raw_payload) -> str:
    """Pull the referenced message id out of a stored raw payload.

    Supports the shapes produced by the FB and WA webhook parsers:
    * FB: {"message": {"reply_to": {"mid": "..."}}}
    * WA: {"context": {"message_id": "..."}}
    Falls back to scanning top-level keys.
    """
    if not raw_payload or not isinstance(raw_payload, dict):
        return ""
    # Facebook Messenger shape
    message = raw_payload.get("message") or {}
    reply_to = message.get("reply_to") or {}
    if isinstance(reply_to, dict) and reply_to.get("mid"):
        return reply_to["mid"]
    # WhatsApp Cloud API shape
    context = raw_payload.get("context") or {}
    if context.get("message_id"):
        return context["message_id"]
    return ""


class Command(BaseCommand):
    help = "Backfill Message.reply_to FKs from stored raw_payload data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would change without writing.",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        candidates = Message.objects.filter(reply_to__isnull=True).exclude(raw_payload={})
        total = candidates.count()
        self.stdout.write(f"Scanning {total} messages with null reply_to…")

        linked = 0
        unresolved = 0
        for msg in candidates.iterator():
            ref_mid = _extract_reply_to_mid(msg.raw_payload)
            if not ref_mid:
                continue
            target = Message.objects.filter(
                connected_account=msg.connected_account,
                external_id=ref_mid,
            ).first()
            if target is None:
                unresolved += 1
                continue
            if dry_run:
                self.stdout.write(f"  would link {msg.id} -> {target.id}")
            else:
                with transaction.atomic():
                    msg.reply_to = target
                    msg.save(update_fields=["reply_to", "updated_at"])
            linked += 1

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"Dry run: would link {linked} messages ({unresolved} had unresolvable refs)."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Linked {linked} reply_to FKs ({unresolved} had unresolvable refs)."
            ))
