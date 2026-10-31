"""Create Celery beat periodic tasks from the per-app registry.

Each app registers its own periodic-task specs (see
``parseus.webapp.registry.periodic_tasks``). This command materializes only the
specs from installed apps into ``django_celery_beat`` PeriodicTask rows, so no
app needs to know another app's task paths.
"""

import json

from django.core.management.base import BaseCommand
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from parseus.webapp.registry import get_periodic_task_specs

_PERIOD_MAP = {
    "microseconds": IntervalSchedule.MICROSECONDS,
    "seconds": IntervalSchedule.SECONDS,
    "minutes": IntervalSchedule.MINUTES,
    "hours": IntervalSchedule.HOURS,
    "days": IntervalSchedule.DAYS,
}


class Command(BaseCommand):
    help = "Create periodic tasks registered by installed apps."

    def handle(self, *args, **options):
        specs = get_periodic_task_specs()
        for spec in specs:
            interval, _ = IntervalSchedule.objects.get_or_create(
                every=spec.every,
                period=_PERIOD_MAP[spec.period],
            )
            defaults = {
                "task": spec.task,
                "interval": interval,
                "queue": spec.queue,
                "enabled": spec.enabled,
            }
            if spec.args:
                defaults["args"] = json.dumps(spec.args)
            PeriodicTask.objects.update_or_create(
                name=spec.name,
                defaults=defaults,
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"PeriodicTask created/updated for {len(specs)} registered task(s)."
            )
        )
