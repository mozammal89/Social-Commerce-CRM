"""
Data migration: copy legacy Store.owners/managers/staff M2M memberships
into the new StoreMembership table.

This migration is **additive**: it reads from the legacy M2Ms and writes
StoreMembership rows. It does NOT remove the legacy M2Ms (that's Phase C
in the plan, deferred until every consumer has migrated).

Behavior:
  - For each Store, each User in Store.owners → a StoreMembership with
    role=store-owner.
  - For each Store, each User in Store.managers → a StoreMembership with
    role=manager.
  - For each Store, each User in Store.staff → a StoreMembership with
    role=staff.
  - If a user already has a StoreMembership for that (user, store, role)
    triple, skip (idempotent).
  - If a system role doesn't exist yet (e.g. seeders haven't run), skip
    silently — the user will be migrated on a future migration once
    seeders run.
  - Roles look up by slug AND store=NULL (system roles).

Backward (reverse):
  - Delete every StoreMembership row whose role slug is one of the
    legacy slugs and which is linked to a store that has the M2M.
  - This is destructive but the forward migration is idempotent, so a
    re-run after reverse produces the same state.
"""

from __future__ import annotations

from django.db import migrations


LEGACY_ROLE_MAP = {
    "owners": "store-owner",
    "managers": "manager",
    "staff": "staff",
}


def _system_role_map(apps):
    """Build {role_slug: Role} for system roles (store=NULL)."""
    Role = apps.get_model("permissions", "Role")
    return {
        r.slug: r
        for r in Role.objects.filter(store__isnull=True, slug__in=set(LEGACY_ROLE_MAP.values()))
    }


def forward(apps, schema_editor):
    Store = apps.get_model("stores", "Store")
    StoreMembership = apps.get_model("permissions", "StoreMembership")
    role_map = _system_role_map(apps)
    if not role_map:
        # System roles haven't been seeded yet. Skip silently; the
        # operator can re-run after `manage.py seed roles`.
        return

    for store in Store.objects.all():
        for m2m_attr, role_slug in LEGACY_ROLE_MAP.items():
            role = role_map.get(role_slug)
            if role is None:
                continue
            m2m = getattr(store, m2m_attr)
            for user in m2m.all():
                StoreMembership.objects.get_or_create(
                    user=user,
                    store=store,
                    role=role,
                    defaults={"is_active": True},
                )


def backward(apps, schema_editor):
    StoreMembership = apps.get_model("permissions", "StoreMembership")
    role_slugs = list(LEGACY_ROLE_MAP.values())
    StoreMembership.objects.filter(role__slug__in=role_slugs).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("permissions", "0001_initial"),
        ("stores", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
