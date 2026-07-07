"""
Seeds the default feature catalog.

Idempotent: running it twice has no effect.
"""

from __future__ import annotations

from apps.core.seeders.base import BaseSeeder
from apps.permissions.constants import DEFAULT_FEATURES
from apps.subscriptions.models import Feature


class FeaturesSeeder(BaseSeeder):
    name = "features"

    def run(self) -> None:
        for code in DEFAULT_FEATURES:
            Feature.objects.update_or_create(
                code=code,
                defaults={
                    "name": code.replace("_", " ").title(),
                    "category": "general",
                    "description": "",
                },
            )
