"""Tests for run-to-run state persistence across scheduled runs.

Commit-4 behaviour: ``run_and_push_analytics`` loads an analytic's run-to-run
state before the run and saves it back after, in a keyed artifact separate from
the trained model, so suppression memory / dedup marks survive a restart.

These exercise the persistence *wiring* (load-before / save-after / save-only-
on-change) with a real :class:`FileArtifactStore` on a tmp path, stubbing the
data-fetching ``run``/``fit`` collaborators so the test stays offline and
deterministic.
"""

from __future__ import annotations

from types import SimpleNamespace

from parseus.analytics.base import Analytic
from parseus.analytics.persistence import FileArtifactStore
from parseus.interfaces import tasks


class _StatefulProbe(Analytic):
    """Minimal analytic whose run appends a marker into its run-to-run state."""

    def __init__(self, pull_duration=0, **kwargs):
        super().__init__(pull_duration=pull_duration, **kwargs)

    @classmethod
    def requires_fit(cls) -> bool:
        return False

    def _run(self, start, end, transformed_documents, state, **other_documents):
        state.add_unique("seen", "marker")
        return []


def _wire(monkeypatch, tmp_path, analytic_cls):
    """Point the runtime at a tmp FileArtifactStore and stub its collaborators."""
    store = FileArtifactStore(tmp_path)
    monkeypatch.setattr(tasks, "get_scheduled_artifact_store", lambda: store)
    monkeypatch.setattr(tasks, "get_ds_client", lambda: object())
    monkeypatch.setattr(
        tasks,
        "get_analytic_config",
        lambda **kwargs: SimpleNamespace(
            init_args={}, out_idx="alerts", suppression="0s"
        ),
    )
    monkeypatch.setattr(tasks, "_fetch_operator_rules", lambda name: [])
    monkeypatch.setattr(tasks, "push_alerts", lambda cfg, alerts: len(list(alerts or [])))

    # Stub the data-fetching run() with one that just drives the analytic's _run,
    # so its state mutates exactly as a real scheduled run would.
    def fake_run(ds_client, analytic, analytic_config):
        return analytic.run_on_data([], start=None, end=None)

    monkeypatch.setattr(tasks, "run", fake_run)
    return store


def test_run_to_run_state_persists_across_runs(monkeypatch, tmp_path):
    store = _wire(monkeypatch, tmp_path, _StatefulProbe)
    state_key = f"{_StatefulProbe.__name__}_celery.state"

    # First run: no state artifact yet, run writes one.
    assert not store.exists(state_key)
    tasks.run_and_push_analytics(_StatefulProbe)
    assert store.exists(state_key)
    assert store.load(state_key)["seen"] == ["marker"]

    # Second run (a "restart"): the marker is loaded back, and add_unique keeps
    # it de-duplicated rather than doubling it.
    tasks.run_and_push_analytics(_StatefulProbe)
    assert store.load(state_key)["seen"] == ["marker"]


class _StatelessProbe(Analytic):
    """Analytic that never touches its run-to-run state."""

    def __init__(self, pull_duration=0, **kwargs):
        super().__init__(pull_duration=pull_duration, **kwargs)

    @classmethod
    def requires_fit(cls) -> bool:
        return False

    def _run(self, start, end, transformed_documents, state, **other_documents):
        return []


def test_state_artifact_not_written_when_state_unchanged(monkeypatch, tmp_path):
    store = _wire(monkeypatch, tmp_path, _StatelessProbe)
    state_key = f"{_StatelessProbe.__name__}_celery.state"

    tasks.run_and_push_analytics(_StatelessProbe)

    # An analytic that evolves no state must not create a state artifact.
    assert not store.exists(state_key)


def test_export_import_state_round_trip():
    probe = _StatefulProbe()
    probe._state.add_unique("seen", "a")
    probe._state.set("flag", True)

    exported = probe.export_state()
    restored = _StatefulProbe()
    restored.import_state(exported)

    assert restored._state.get("seen") == ["a"]
    assert restored._state.get("flag") is True


def test_run_to_run_state_excluded_from_model_state_dict():
    probe = _StatefulProbe()
    probe._state.set("flag", True)

    # The trained-model payload must not carry the run-to-run StateStore.
    assert "_state" not in probe.state_dict()
