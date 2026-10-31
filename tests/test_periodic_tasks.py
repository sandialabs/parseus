"""Tests for per-app periodic-task registration and the build command."""

import pytest

from parseus.webapp.registry import (
    PeriodicTaskSpec,
    clear_periodic_task_specs,
    get_periodic_task_specs,
    register_periodic_tasks,
)


def _restore_app_specs():
    from parseus.webapp.alerts import periodic_tasks as alerts_pt
    from parseus.webapp.analytics import periodic_tasks as analytics_pt

    analytics_pt.register()
    alerts_pt.register()


def test_spec_validation():
    with pytest.raises(ValueError):
        PeriodicTaskSpec(name="x", task="t", every=1, period="fortnights", queue="q")
    with pytest.raises(ValueError):
        PeriodicTaskSpec(name="x", task="t", every=0, period="seconds", queue="q")


def test_apps_register_their_specs():
    """Both analytics and alerts contribute their own specs."""
    _restore_app_specs()
    names = {spec.name for spec in get_periodic_task_specs()}
    # analytics-owned
    assert {"run-ip-analyic", "run-scpi-analyic"} <= names
    # alerts-owned
    assert {"run-logrotate", "check-gpib-ingestor-health"} <= names


def test_analytics_specs_do_not_reference_alerts_tasks():
    """analytics periodic tasks must only name analytics task paths."""
    from parseus.webapp.analytics import periodic_tasks as analytics_pt

    for spec in analytics_pt.build_specs():
        assert spec.task.startswith("parseus.webapp.analytics.tasks")


def test_alerts_specs_only_reference_alerts_tasks():
    from parseus.webapp.alerts import periodic_tasks as alerts_pt

    for spec in alerts_pt.build_specs():
        assert spec.task.startswith("parseus.webapp.alerts.tasks")


def test_command_source_has_no_hardcoded_task_paths():
    """The command builds from the registry, not hard-coded per-app task paths."""
    import inspect

    from parseus.webapp.analytics.management.commands import create_periodic_tasks

    source = inspect.getsource(create_periodic_tasks)
    assert "parseus.webapp.alerts.tasks" not in source
    assert "parseus.webapp.analytics.tasks" not in source
    assert "get_periodic_task_specs" in source


def test_registry_clear_and_reregister():
    clear_periodic_task_specs()
    assert get_periodic_task_specs() == ()
    register_periodic_tasks(
        PeriodicTaskSpec(name="only", task="t", every=1, period="hours", queue="q")
    )
    assert len(get_periodic_task_specs()) == 1
    clear_periodic_task_specs()
    _restore_app_specs()
