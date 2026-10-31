"""Periodic (Celery beat) task specs owned by the alerts app."""

from __future__ import annotations

from parseus.webapp.registry import PeriodicTaskSpec, register_periodic_tasks


def build_specs() -> list[PeriodicTaskSpec]:
    """Return the alerts app's maintenance / ingestor-health tasks."""
    return [
        PeriodicTaskSpec(
            name="run-logrotate",
            task="parseus.webapp.alerts.tasks.run_logrotate",
            every=1,
            period="days",
            queue="maintenance",
        ),
        PeriodicTaskSpec(
            name="run-cleanup-ftp-files",
            task="parseus.webapp.alerts.tasks.cleanup_ftp_files",
            every=1,
            period="hours",
            queue="maintenance",
        ),
        PeriodicTaskSpec(
            name="check-logstash-ingestor-health",
            task="parseus.webapp.alerts.tasks.check_logstash_ingestor_health",
            every=5,
            period="minutes",
            queue="maintenance",
        ),
        PeriodicTaskSpec(
            name="check-gpib-ingestor-health",
            task="parseus.webapp.alerts.tasks.check_gpib_ingestor_health",
            every=5,
            period="minutes",
            queue="maintenance",
        ),
    ]


def register() -> None:
    """Register the alerts periodic-task specs."""
    register_periodic_tasks(*build_specs())
