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
}


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    pass
