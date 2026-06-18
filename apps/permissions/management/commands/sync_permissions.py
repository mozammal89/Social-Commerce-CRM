"""
sync_permissions — diff the resource registry against the DB and reconcile.

Idempotent. Safe to run on every deploy.

Behavior:

- Resources are upserted from ``apps.permissions.registry.RESOURCES``.
- Permissions are upserted from ``iter_permissions()``.
- Resources / permissions removed from the registry are NOT auto-deleted
  in the DB; this prevents accidental role/permisson destruction. Use
  ``--prune`` to actually remove them (requires ``--confirm``).

Flags:

  --check       exit non-zero if any new resource/permission would be added.
  --prune       remove DB rows that are no longer in the registry.
  --confirm     required with --prune to actually delete.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.permissions.models import Permission, Resource
from apps.permissions.registry import RESOURCES, iter_permissions


class Command(BaseCommand):
    help = "Reconcile the resource registry against the Resource/Permission tables."

    def add_arguments(self, parser):
        parser.add_argument(
            "--check",
            action="store_true",
            help="Exit non-zero if any drift is found (CI-friendly).",
        )
        parser.add_argument(
            "--prune",
            action="store_true",
            help="Delete Resource/Permission rows no longer in the registry.",
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Required with --prune to actually delete rows.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        check = options.get("check", False)
        prune = options.get("prune", False)
        confirm = options.get("confirm", False)

        created_r = updated_r = 0
        created_p = updated_p = 0

        # 1) Resources
        for code, spec in RESOURCES.items():
            _, created = Resource.objects.update_or_create(
                code=code,
                defaults={
                    "name": spec["name"],
                    "category": spec.get("category", "general"),
                    "description": spec.get("description", ""),
                    "is_active": True,
                    "actions": spec["actions"],
                },
            )
            if created:
                created_r += 1
            else:
                updated_r += 1

        # 2) Permissions
        for spec in iter_permissions():
            resource = Resource.objects.get(code=spec["resource"])
            _, created = Permission.objects.update_or_create(
                code=spec["code"],
                defaults={
                    "resource": resource,
                    "action": spec["action"],
                    "name": spec["name"],
                    "description": spec["description"],
                    "is_system": True,
                },
            )
            if created:
                created_p += 1
            else:
                updated_p += 1

        # 3) Optional prune
        deleted_r = deleted_p = 0
        if prune and confirm:
            registered_resource_codes = set(RESOURCES.keys())
            registered_perm_codes = {p["code"] for p in iter_permissions()}

            deleted_r, _ = (
                Resource.objects.exclude(code__in=registered_resource_codes)
                .delete()
            )
            deleted_p, _ = (
                Permission.objects.exclude(code__in=registered_perm_codes).delete()
            )
        elif prune and not confirm:
            self.stdout.write(
                self.style.WARNING("--prune requires --confirm; skipping deletion.")
            )

        msg = (
            f"Resources: +{created_r} ~{updated_r}"
            + (f" -{deleted_r}" if deleted_r else "")
            + f" | Permissions: +{created_p} ~{updated_p}"
            + (f" -{deleted_p}" if deleted_p else "")
        )

        if check and (created_r or created_p):
            self.stdout.write(self.style.WARNING(f"Drift detected: {msg}"))
            raise SystemExit(1)

        if check:
            self.stdout.write(self.style.SUCCESS("Registry in sync."))
        else:
            self.stdout.write(self.style.SUCCESS(msg))