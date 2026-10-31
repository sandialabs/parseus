"""Phase 0 characterization tests for the analytics core refactor.

These tests intentionally pin down *current* end-to-end behavior of representative
analytics across the four dimensions the refactor will touch:

    - data source (Elasticsearch-shaped documents vs PEAT result data),
    - training (supervised requires_fit vs unsupervised),
    - state (stateful vs stateless run-to-run behaviour),
    - persistence (the pickle save/load round-trip).

They are a safety net: later phases (base.py split, versioned persistence, state
contract enforcement) must keep these observable behaviors stable, or consciously
update these tests when a behavior is deliberately changed.

Everything here runs offline -- no live datastore -- using in-memory documents and
aggregation buckets shaped the way the runtime feeds them today.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pandas as pd

from parseus.analytics.base import Analytic
from parseus.analytics.host_anomalies.sysmon_unapproved_ip_analytic import (
    SysmonUnapprovedIpAnalytic,
)
from parseus.analytics.network_anomalies.excessive_conversation_analytic import (
    ExcessiveConversationAnalytic,
)


# ---------------------------------------------------------------------------
# Helpers: build the composite-aggregation buckets the datastore layer returns
# for ExcessiveConversationAnalytic (see build_interval_counter).
# ---------------------------------------------------------------------------
def _conversation_buckets(source_ip: str, dest_counts_by_epoch_ms: dict[int, int]):
    """Return composite-agg buckets shaped like the ES datastore output."""
    return [
        {
            "key": {"timestamp": epoch_ms, "source_ips": source_ip},
            "destination_ips": {"value": count},
        }
        for epoch_ms, count in dest_counts_by_epoch_ms.items()
    ]


def _make_trained_excess_conversation_analytic() -> ExcessiveConversationAnalytic:
    """Fit a supervised+stateful analytic on deterministic in-memory data."""
    analytic = ExcessiveConversationAnalytic(calendar_interval="minute")
    # A steady baseline so the trained mean/stddev are well defined.
    minute = 60_000
    training = _conversation_buckets(
        "10.0.0.5",
        {minute * i: 2 for i in range(1, 11)},
    )
    analytic.fit(training)
    return analytic


# ---------------------------------------------------------------------------
# Training dimension: requires_fit is the current supervised/unsupervised switch.
# ---------------------------------------------------------------------------
def test_requires_fit_flags_are_stable_across_representative_analytics():
    # Supervised (must be fit before use today).
    assert ExcessiveConversationAnalytic.requires_fit() is True
    # Unsupervised host analytic (runs without training).
    assert SysmonUnapprovedIpAnalytic.requires_fit() is False


# ---------------------------------------------------------------------------
# Supervised + stateful: fit produces a baseline, run emits alerts.
# ---------------------------------------------------------------------------
def test_excess_conversation_fit_populates_training_state():
    analytic = _make_trained_excess_conversation_analytic()

    # The trained statistics table is what pickling must preserve.
    assert not analytic.logic_.stats_df.empty
    assert "10.0.0.5" in analytic.logic_.stats_df.index
    assert set(analytic.logic_.stats_df.columns) == {"mean", "std"}


def test_excess_conversation_run_emits_alert_for_outlier():
    analytic = _make_trained_excess_conversation_analytic()

    minute = 60_000
    # A window where the source talks to far more peers than the trained mean.
    run_buckets = _conversation_buckets("10.0.0.5", {minute * 11: 50})
    start = datetime(2024, 1, 1, 0, 0, 0)
    end = datetime(2024, 1, 1, 0, 1, 0)

    alerts = analytic.run_on_data(run_buckets, start=start, end=end)

    assert len(alerts) == 1

    alert = alerts[0]
    assert alert["event"]["kind"] == "alert"
    assert alert["event"]["action"] == "excess device conversations"
    assert alert["source"]["ip"] == "10.0.0.5"

    # Common fields are stamped by run_on_data.
    assert alert["agent"]["type"] == "ExcessiveConversationAnalytic"
    assert isinstance(alert["event"]["uuid"], uuid.UUID)
    assert "created" in alert["event"]


# ---------------------------------------------------------------------------
# Persistence: the versioned artifact save/load round-trip must preserve
# trained state.
# ---------------------------------------------------------------------------
def test_artifact_round_trip_preserves_trained_statistics(tmp_path):
    analytic = _make_trained_excess_conversation_analytic()
    original_stats = analytic.logic_.stats_df.copy()

    model_path = tmp_path / "excess_conversation.joblib"
    analytic.save(str(model_path))

    assert model_path.exists()

    reloaded = ExcessiveConversationAnalytic(calendar_interval="minute")
    reloaded.load(str(model_path))

    pd.testing.assert_frame_equal(reloaded.logic_.stats_df, original_stats)
    # load_window_ is a trailing-underscore ("_save_fields") attribute.
    assert reloaded.load_window_ == analytic.load_window_


def test_reloaded_analytic_runs_and_matches_fresh_analytic(tmp_path):
    fresh = _make_trained_excess_conversation_analytic()

    model_path = tmp_path / "excess_conversation.joblib"
    fresh.save(str(model_path))
    reloaded = ExcessiveConversationAnalytic(calendar_interval="minute")
    reloaded.load(str(model_path))

    minute = 60_000
    run_buckets = _conversation_buckets("10.0.0.5", {minute * 11: 50})
    start = datetime(2024, 1, 1, 0, 0, 0)
    end = datetime(2024, 1, 1, 0, 1, 0)

    fresh_alerts = fresh.run_on_data(run_buckets, start=start, end=end)
    reloaded_alerts = reloaded.run_on_data(run_buckets, start=start, end=end)

    # Same alert kinds and the same set of alerting source IPs.
    def kinds(alerts):
        return sorted(a.get("event", {}).get("kind") for a in alerts)

    def source_ips(alerts):
        return sorted(a["source"]["ip"] for a in alerts if "source" in a)

    assert kinds(fresh_alerts) == kinds(reloaded_alerts)
    assert source_ips(fresh_alerts) == source_ips(reloaded_alerts)


# ---------------------------------------------------------------------------
# Data source + stateless: the Sysmon (Elasticsearch winlog) analytic emits one
# alert per raw document and preserves order/timestamps. Golden alert shape.
# ---------------------------------------------------------------------------
def test_sysmon_ip_analytic_alert_document_shape_is_stable():
    analytic = SysmonUnapprovedIpAnalytic(known_good_ips=[])
    docs = [
        {
            "@timestamp": "2026-01-01T00:00:01Z",
            "winlog": {"event_data": {"SourceAddress": "192.0.2.10"}},
        },
    ]

    alerts = analytic.run_on_data(docs, start=None, end=None)

    assert len(alerts) == 1
    alert = alerts[0]
    # Domain fields produced by the analytic.
    assert alert["@timestamp"] == "2026-01-01T00:00:01Z"
    assert alert["source"]["ip"] == "192.0.2.10"
    # Common fields stamped by the base class.
    assert alert["agent"]["type"] == "SysmonUnapprovedIpAnalytic"
    assert alert["acknowledge"]["reason"] == "none"
    assert isinstance(alert["event"]["uuid"], uuid.UUID)


# ---------------------------------------------------------------------------
# Persistence internals: _save_fields is the "what gets persisted" contract
# used by state_dict().
# ---------------------------------------------------------------------------
def test_save_fields_selects_trailing_underscore_attributes():
    class _SaveFieldsAnalytic(Analytic):
        """Minimal concrete analytic (Analytic._run is abstract)."""

        def _run(self, start, end, transformed_documents, state, **other_documents):
            return []

    analytic = _SaveFieldsAnalytic(pull_duration=5)

    save_fields = analytic._save_fields

    # Single-trailing-underscore attributes are saved; dunders are excluded.
    assert "load_window_" in save_fields
    assert not any(field.endswith("__") for field in save_fields)


# ---------------------------------------------------------------------------
# PEAT data source + supervised + stateful: pin the trained-state artifact
# round-trip. We drive _fit directly with the (device_id, epoch) tuple shape the
# analytic stores, avoiding the filesystem PEAT transform while still locking
# the persistence behavior.
# ---------------------------------------------------------------------------
def test_peat_device_change_artifact_round_trip_preserves_training_set(tmp_path):
    from parseus.analytics.ot_internals.peat_device_change_analytic import (
        PeatDeviceChangeAnalytic,
    )

    analytic = PeatDeviceChangeAnalytic()
    training_devices = [("plc-1", 1_700_000_000), ("hmi-2", 1_700_000_100)]
    analytic._fit(training_devices)

    assert analytic.training_device_set_ == set(training_devices)

    model_path = tmp_path / "peat_device_change.joblib"
    analytic.save(str(model_path))

    reloaded = PeatDeviceChangeAnalytic()
    reloaded.load(str(model_path))

    assert reloaded.training_device_set_ == analytic.training_device_set_

