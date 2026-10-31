"""Registry of per-app Celery beat (periodic) task specifications.

Each app that ships scheduled work registers its own periodic-task specs, so
the project's ``create_periodic_tasks`` management command can assemble the beat
schedule from only the apps that are installed -- instead of one app hard-coding
another app's task paths.

A :class:`PeriodicTaskSpec` is intentionally storage-agnostic: it names an
interval as ``(every, period)`` (e.g. ``(30, "seconds")``) and the command maps
that onto ``django_celery_beat`` schedules. Apps register their specs (typically
in ``AppConfig.ready``) via :func:`register_periodic_tasks`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "PeriodicTaskSpec",
    "register_periodic_tasks",
    "get_periodic_task_specs",
    "clear_periodic_task_specs",
]

# Allowed period units, matching django_celery_beat.IntervalSchedule periods.
_ALLOWED_PERIODS = {"microseconds", "seconds", "minutes", "hours", "days"}


@dataclass(frozen=True)
class PeriodicTaskSpec:
    """One periodic task an app wants scheduled.

    ``name``     -- unique PeriodicTask name.
    ``task``     -- dotted Celery task path.
    ``every``    -- interval count.
    ``period``   -- interval unit (e.g. ``"seconds"``, ``"hours"``, ``"days"``).
    ``queue``    -- Celery queue name.
    ``args``     -- positional task args (JSON-serializable list).
    ``enabled``  -- whether the task starts enabled.
    """

    name: str
    task: str
    every: int
    period: str
    queue: str
    args: list[Any] = field(default_factory=list)
    enabled: bool = False

    def __post_init__(self) -> None:
        if self.period not in _ALLOWED_PERIODS:
            raise ValueError(
                f"Invalid period '{self.period}'. Expected one of "
                f"{sorted(_ALLOWED_PERIODS)}."
            )
        if self.every <= 0:
            raise ValueError("PeriodicTaskSpec.every must be positive")


# Registered task specs keyed by their unique name (idempotent registration).
_SPECS: dict[str, PeriodicTaskSpec] = {}


def register_periodic_tasks(*specs: PeriodicTaskSpec) -> None:
    """Register (or replace) one or more periodic-task specs by name."""
    for spec in specs:
        if not isinstance(spec, PeriodicTaskSpec):
            raise TypeError("specs must be PeriodicTaskSpec instances")
        _SPECS[spec.name] = spec


def get_periodic_task_specs() -> tuple[PeriodicTaskSpec, ...]:
    """Return all registered periodic-task specs."""
    return tuple(_SPECS.values())


def clear_periodic_task_specs() -> None:
    """Remove all registered specs (primarily for tests)."""
    _SPECS.clear()
