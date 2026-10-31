"""Unit tests for the configurable alert-suppression window.

These pin the engine-core :mod:`parseus.analytics.core.suppression` behaviour in
isolation (no analytic wiring yet):

    1. window parsing (short-form durations, ``infinite``, the ``0s`` default);
    2. fingerprint stability and sensitivity;
    3. the three emit/suppress behaviours (never / finite / infinite);
    4. decisions ride on the StateStore and survive an as_dict/from_dict round
       trip (the property the runtime relies on to persist suppression).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from parseus.analytics.core.state import StateStore
from parseus.analytics.core.suppression import (
    DEFAULT_WINDOW,
    SuppressionWindow,
    SuppressionWindowError,
    finding_fingerprint,
    parse_window,
)

_NOW = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 1. Window parsing.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text, expected_seconds",
    [
        ("0s", 0),
        ("30s", 30),
        ("15m", 15 * 60),
        ("24h", 24 * 60 * 60),
        ("7d", 7 * 24 * 60 * 60),
        ("2w", 2 * 7 * 24 * 60 * 60),
        ("  24H  ", 24 * 60 * 60),  # whitespace + case insensitive
    ],
)
def test_parse_window_durations(text, expected_seconds):
    assert parse_window(text) == expected_seconds


def test_parse_window_infinite_is_none():
    assert parse_window("infinite") is None
    assert parse_window("INFINITE") is None


def test_parse_window_default_is_zero_seconds():
    assert parse_window(None) == 0
    assert parse_window(DEFAULT_WINDOW) == 0


@pytest.mark.parametrize("bad", ["", "24", "10x", "abc", "-5m", "1.5h"])
def test_parse_window_rejects_garbage(bad):
    with pytest.raises(SuppressionWindowError):
        parse_window(bad)


def test_parse_window_rejects_non_string():
    with pytest.raises(SuppressionWindowError):
        parse_window(24)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. Fingerprint stability and sensitivity.
# ---------------------------------------------------------------------------
def test_fingerprint_is_stable_for_equal_parts():
    assert finding_fingerprint("alice", "10.0.0.1") == finding_fingerprint(
        "alice", "10.0.0.1"
    )


def test_fingerprint_changes_with_parts_and_order():
    assert finding_fingerprint("alice") != finding_fingerprint("bob")
    assert finding_fingerprint("a", "b") != finding_fingerprint("b", "a")


def test_fingerprint_normalises_types_and_none():
    # Different parts must not collide just because str() would look similar.
    assert finding_fingerprint(1, 2) != finding_fingerprint(12)
    assert finding_fingerprint(None) == finding_fingerprint(None)


# ---------------------------------------------------------------------------
# 3. Emit / suppress behaviour.
# ---------------------------------------------------------------------------
def test_window_zero_always_emits():
    window = SuppressionWindow(StateStore(), "0s")
    assert window.should_emit("alice", now=_NOW) is True
    # Same finding, same instant: still emits (never suppress).
    assert window.should_emit("alice", now=_NOW) is True


def test_finite_window_suppresses_within_and_reemits_after():
    window = SuppressionWindow(StateStore(), "24h")

    assert window.should_emit("alice", now=_NOW) is True
    # Within the window: suppressed.
    assert window.should_emit("alice", now=_NOW + timedelta(hours=1)) is False
    assert window.should_emit("alice", now=_NOW + timedelta(hours=23)) is False
    # At/after the window boundary: re-emits.
    assert window.should_emit("alice", now=_NOW + timedelta(hours=24)) is True
    # ...and the window restarts from that new emission.
    assert window.should_emit("alice", now=_NOW + timedelta(hours=25)) is False


def test_finite_window_is_per_fingerprint():
    window = SuppressionWindow(StateStore(), "24h")
    assert window.should_emit("alice", now=_NOW) is True
    # A different finding is unaffected by alice's suppression.
    assert window.should_emit("bob", now=_NOW) is True
    assert window.should_emit("alice", now=_NOW + timedelta(hours=1)) is False


def test_infinite_window_emits_once_then_suppresses_forever():
    window = SuppressionWindow(StateStore(), "infinite")
    assert window.should_emit("alice", now=_NOW) is True
    assert window.should_emit("alice", now=_NOW + timedelta(days=365)) is False


# ---------------------------------------------------------------------------
# 4. Suppression rides on the StateStore and survives a round trip.
# ---------------------------------------------------------------------------
def test_decisions_persist_through_state_round_trip():
    state = StateStore()
    first = SuppressionWindow(state, "24h")
    assert first.should_emit("alice", now=_NOW) is True

    # Simulate a scheduled-run restart: serialise the state and rebuild it.
    restored = StateStore.from_dict(state.as_dict())
    second = SuppressionWindow(restored, "24h")

    # The prior emission is remembered across the round trip -> suppressed.
    assert second.should_emit("alice", now=_NOW + timedelta(hours=1)) is False
    # After the window, it re-emits.
    assert second.should_emit("alice", now=_NOW + timedelta(hours=25)) is True


def test_unparseable_stored_timestamp_fails_open():
    # A corrupted/legacy timestamp must not silently hide alerts.
    state = StateStore()
    window = SuppressionWindow(state, "24h")
    window.should_emit("alice", now=_NOW)

    emissions = state.get("_suppression_emissions")
    (only_key,) = emissions.keys()
    emissions[only_key] = "not-a-timestamp"

    assert window.should_emit("alice", now=_NOW + timedelta(minutes=1)) is True
