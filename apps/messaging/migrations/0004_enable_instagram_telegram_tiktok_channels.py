"""
Enable the channels whose adapters ship with this release.

Instagram Direct, Telegram and TikTok Business Messaging were seeded
into the channel catalog (by ``sync_channels``) as ``is_enabled=False``
because their adapters did not exist yet. The adapter implementations
landed in this release (see ``apps/messaging/adapters/{instagram,
telegram,tiktok}/``), so the catalog rows are flipped on here.

``sync_channels`` deliberately never overwrites ``is_enabled`` on
existing rows (so a super-admin's manual toggle is respected on re-
sync); this migration is the one-shot data change that ships with the
adapter code. A super-admin can still disable any of these channels
after the migration via the Platform Channels UI — re-syncing will not
re-enable them.
"""

from django.db import migrations

# (channel_type, adapter_class) pairs to enable. Kept in sync with
# apps/messaging/constants.DEFAULT_CHANNELS — the adapter_class matches
# the dotted path registered there, so we only flip a row on when its
# adapter is actually wired (defensive against a partial rollout).
CHANNELS_TO_ENABLE = [
    (
        "instagram",
        "apps.messaging.adapters.instagram.adapter.InstagramAdapter",
    ),
    (
        "telegram",
        "apps.messaging.adapters.telegram.adapter.TelegramAdapter",
    ),
    (
        "tiktok",
        "apps.messaging.adapters.tiktok.adapter.TikTokAdapter",
    ),
]


def enable_channels_with_adapters(apps, schema_editor):
    """Flip ``is_enabled=True`` for each channel whose adapter now exists.

    Only touches rows whose ``adapter_class`` matches the expected path —
    so an admin who cleared the adapter_class on purpose is left alone.
    """
    Channel = apps.get_model("messaging", "Channel")
    for channel_type, adapter_class in CHANNELS_TO_ENABLE:
        Channel.objects.filter(
            channel_type=channel_type,
            adapter_class=adapter_class,
        ).update(is_enabled=True)


def disable_channels_with_adapters(apps, schema_editor):
    """Reverse: disable the channels enabled by the forward migration.

    Restores the pre-migration "adapter not yet built" state. Existing
    connected accounts are untouched — only the catalog availability
    flips back.
    """
    Channel = apps.get_model("messaging", "Channel")
    channel_types = [ct for ct, _ in CHANNELS_TO_ENABLE]
    Channel.objects.filter(channel_type__in=channel_types).update(is_enabled=False)


class Migration(migrations.Migration):
    dependencies = [
        ("messaging", "0003_customer_identity_sync_fields"),
    ]

    operations = [
        migrations.RunPython(
            enable_channels_with_adapters,
            reverse_code=disable_channels_with_adapters,
        ),
    ]
