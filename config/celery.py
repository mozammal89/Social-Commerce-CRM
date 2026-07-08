"""
Celery configuration for Social Commerce CRM project.
"""

import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

app = Celery("social_commerce_crm")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f"Request: {self.request!r}")


app.conf.beat_schedule = {
    "cleanup-refresh-tokens": {
        "task": "apps.accounts.tasks.cleanup_refresh_tokens",
        "schedule": crontab(hour=0, minute=0),
    },
    "renew-due-subscriptions-hourly": {
        "task": "apps.permissions.tasks.renew_due_subscriptions",
        # Runs before the expire sweeps so a renewed row (with a fresh
        # ``current_period_end`` in the future) is no longer matched by
        # ``expire_active_periods``. If renewal raises, the row is left
        # with its old period end and the :30 sweep degrades gracefully
        # to the existing expire behavior.
        "schedule": crontab(minute=5),  # every hour at :05
    },
    "expire-trials-hourly": {
        "task": "apps.permissions.tasks.expire_trials",
        "schedule": crontab(minute=15),  # every hour at :15
    },
    "expire-active-periods-hourly": {
        "task": "apps.permissions.tasks.expire_active_periods",
        "schedule": crontab(minute=30),  # every hour at :30
    },
    "escalate-past-due-daily": {
        "task": "apps.permissions.tasks.escalate_past_due",
        "schedule": crontab(hour=2, minute=0),  # 02:00 daily
        "kwargs": {"grace_days": 7},
    },

}


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    pass
