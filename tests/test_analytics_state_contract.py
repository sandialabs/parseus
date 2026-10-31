"""Phase 5a: run-to-run state contract characterization tests.

These pin the behaviour of the explicit :class:`StateStore` state contract that
replaced the ``_run`` / ``_run_stateful`` split and the ``self.previous_state``
sentinel:

    1. baseline alerts are emitted only on the first run, gated by state;
    2. the OT function-code analytic's "already alerted" markers accumulate in
       state across runs (a repeat anomaly is not re-alerted);
    3. the StateStore round-trips through ``as_dict`` / ``from_dict``;
    4. the ``_run`` contract is enforced — a concrete analytic that omits
       ``_run`` cannot be instantiated.

Everything runs offline using in-memory documents shaped the way the runtime
feeds them today.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from parseus.analytics.base import Analytic
from parseus.analytics.core.state import StateStore
from parseus.analytics.network_anomalies.excessive_conversation_analytic import (
    ExcessiveConversationAnalytic,
)
from parseus.analytics.network_anomalies.port_scan_target_analytic import (
    PortScanTargetAnalytic,
)


MINUTE_MS = 60_000
_START = datetime(2024, 1, 1, 0, 0, 0)
_END = datetime(2024, 1, 1, 0, 1, 0)


# ---------------------------------------------------------------------------
# Fixture builders — composite-agg buckets shaped like the ES datastore output.
# ---------------------------------------------------------------------------
def _nested_buckets(outer_key: str, outer_ip: str, inner_metric: str, by_epoch_ms):
    return [
        {
            "key": {"timestamp": epoch_ms, outer_key: outer_ip},
            inner_metric: {"value": value},
        }
        for epoch_ms, value in by_epoch_ms.items()
    ]


def _trained_excess_conversation(suppression="0s") -> ExcessiveConversationAnalytic:
    analytic = ExcessiveConversationAnalytic(
        calendar_interval="minute",
        suppression=suppression,
    )
    training = _nested_buckets(
        "source_ips", "10.0.0.5", "destination_ips",
        {MINUTE_MS * i: 2 for i in range(1, 11)},
    )
    analytic.fit(training)
    return analytic


def _trained_port_scan(suppression="0s") -> PortScanTargetAnalytic:
    analytic = PortScanTargetAnalytic(
        calendar_interval="minute",
        suppression=suppression,
    )
    training = _nested_buckets(
        "dest_ips", "10.0.0.9", "destination_ports",
        {MINUTE_MS * i: 2 for i in range(1, 11)},
    )
    analytic.fit(training)
    return analytic


def _kinds(alerts):
    return [alert.get("event", {}).get("kind") for alert in alerts]


@pytest.mark.parametrize(
    "make_analytic, outer_key, outer_ip, inner_metric",
    [
        (_trained_excess_conversation, "source_ips", "10.0.0.5", "destination_ips"),
        (_trained_port_scan, "dest_ips", "10.0.0.9", "destination_ports"),
    ],
)
def test_default_suppression_window_alerts_every_run(
    make_analytic, outer_key, outer_ip, inner_metric
):
    analytic = make_analytic()
    run_buckets = _nested_buckets(
        outer_key, outer_ip, inner_metric, {MINUTE_MS * 11: 50}
    )

    first = analytic.run_on_data(run_buckets, start=_START, end=_END)
    second = analytic.run_on_data(run_buckets, start=_START, end=_END)

    assert _kinds(first) == ["alert"]
    assert _kinds(second) == ["alert"]


@pytest.mark.parametrize(
    "make_analytic, outer_key, outer_ip, inner_metric",
    [
        (_trained_excess_conversation, "source_ips", "10.0.0.5", "destination_ips"),
        (_trained_port_scan, "dest_ips", "10.0.0.9", "destination_ports"),
    ],
)
def test_finite_suppression_window_suppresses_repeat_then_reemits(
    make_analytic, outer_key, outer_ip, inner_metric
):
    analytic = make_analytic(suppression="24h")
    run_buckets = _nested_buckets(
        outer_key, outer_ip, inner_metric, {MINUTE_MS * 11: 50}
    )

    first = analytic.run_on_data(run_buckets, start=_START, end=_END)
    within = analytic.run_on_data(
        run_buckets,
        start=_START,
        end=_END,
    )
    after = analytic.run_on_data(
        run_buckets,
        start=_START + timedelta(hours=25),
        end=_END + timedelta(hours=25),
    )

    assert _kinds(first) == ["alert"]
    assert _kinds(within) == []
    assert _kinds(after) == ["alert"]


def test_suppression_window_is_tracked_in_state_not_on_self():
    analytic = _trained_excess_conversation(suppression="24h")

    assert not hasattr(analytic, "previous_state")

    run_buckets = _nested_buckets(
        "source_ips", "10.0.0.5", "destination_ips", {MINUTE_MS * 11: 50}
    )
    analytic.run_on_data(run_buckets, start=_START, end=_END)

    state = analytic.export_state()

    assert "baseline_emitted" not in state
    assert "_suppression_emissions" in state
    assert len(state["_suppression_emissions"]) == 1


def test_state_store_round_trips_through_dict():
    store = StateStore()
    store.set("baseline_emitted", True)
    store.add_unique("covered_alerts", "10.0.0.1_10.0.0.2:modbus:1")
    store.add_unique("covered_alerts", "10.0.0.1_10.0.0.2:modbus:1")  # duplicate
    store.add_unique("covered_alerts", "10.0.0.3_10.0.0.4:dnp3:2")

    restored = StateStore.from_dict(store.as_dict())

    assert restored.get("baseline_emitted") is True
    # Ordered, de-duplicated list (not a set): order preserved, no duplicates.
    assert restored.get("covered_alerts") == [
        "10.0.0.1_10.0.0.2:modbus:1",
        "10.0.0.3_10.0.0.4:dnp3:2",
    ]


def test_state_store_add_unique_reports_novelty_and_lists_are_ordered():
    store = StateStore()
    assert store.add_unique("seen", "a") is True
    assert store.add_unique("seen", "a") is False
    assert store.add_unique("seen", "b") is True
    assert store.get("seen") == ["a", "b"]
    assert store.contains("seen", "b") is True
    assert store.contains("seen", "missing") is False


def test_state_store_as_dict_is_a_defensive_copy():
    store = StateStore()
    store.add_unique("seen", "a")

    snapshot = store.as_dict()
    snapshot["seen"].append("mutation")

    # Mutating the snapshot must not affect the live store.
    assert store.get("seen") == ["a"]


def test_analytic_without_run_cannot_be_instantiated():
    class NoRunAnalytic(Analytic):
        """Concrete analytic that omits the required _run."""

    with pytest.raises(TypeError):
        NoRunAnalytic(pull_duration=1)


def test_analytic_with_run_can_be_instantiated():
    class HasRunAnalytic(Analytic):
        def _run(self, start, end, transformed_documents, state, **other_documents):
            return []

    analytic = HasRunAnalytic(pull_duration=1)
    assert analytic.run_on_data([], start=None, end=None) == []
