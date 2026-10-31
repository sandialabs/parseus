"""Periodic (Celery beat) task specs owned by the analytics app."""

from __future__ import annotations

from parseus.webapp.registry import PeriodicTaskSpec, register_periodic_tasks

_ANALYTIC_RUNNER = "parseus.webapp.analytics.tasks.analytic_runner"


def build_specs() -> list[PeriodicTaskSpec]:
    """Return the analytics app's scheduled analytic runners."""
    return [
        PeriodicTaskSpec(
            name="run-ip-analyic",
            task=_ANALYTIC_RUNNER,
            every=30,
            period="seconds",
            queue="analytics",
            args=["SysmonUnapprovedIpAnalytic"],
        ),
        PeriodicTaskSpec(
            name="run-device-analyic",
            task=_ANALYTIC_RUNNER,
            every=30,
            period="seconds",
            queue="analytics",
            args=["SysmonUnapprovedDeviceAnalytic"],
        ),
        PeriodicTaskSpec(
            name="run-user-analyic",
            task=_ANALYTIC_RUNNER,
            every=30,
            period="seconds",
            queue="analytics",
            args=["SysmonUnapprovedUserAnalytic"],
        ),
        PeriodicTaskSpec(
            name="run-scpi-analyic",
            task=_ANALYTIC_RUNNER,
            every=1,
            period="days",
            queue="analytics",
            args=["ScpiCompareAnalytic"],
        ),
        PeriodicTaskSpec(
            name="run-scpi-value-ranges-analyic",
            task=_ANALYTIC_RUNNER,
            every=1,
            period="days",
            queue="analytics",
            args=["ScpiValueRangesAnalytic"],
        ),
    ]


def register() -> None:
    """Register the analytics periodic-task specs."""
    register_periodic_tasks(*build_specs())
