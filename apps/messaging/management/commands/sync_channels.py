"""
Seed/sync the global ``Channel`` catalog from ``DEFAULT_CHANNELS``.

Idempotent: safe to run repeatedly. Creates missing channel rows and
updates existing ones (capabilities, adapter_class, sort_order) to match
the registry, but never deletes rows — a row removed from the registry
stays in the DB so connected accounts keep a valid FK.

Usage::

    python manage.py sync_channels
"""

from django.core.management.base import BaseCommand

from apps.messaging.constants import DEFAULT_CAPABILITIES, DEFAULT_CHANNELS
from apps.messaging.models import Channel


class Command(BaseCommand):
    help = "Seed/sync the global messaging channel catalog."

    def handle(self, *args, **options):
        created = 0
        updated = 0
        for spec in DEFAULT_CHANNELS:
            slug = spec["slug"]
            capabilities = DEFAULT_CAPABILITIES.get(slug, [])
            obj, was_created = Channel.objects.update_or_create(
                slug=slug,
                defaults={
                    "channel_type": spec["channel_type"],
                    "name": spec["name"],
                    "adapter_class": spec.get("adapter_class", ""),
                    "capabilities": capabilities,
                    "sort_order": spec.get("sort_order", 100),
                    "is_enabled": True,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1
        total = Channel.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f"Channels: +{created} ~{updated} | total={total}"
        ))
