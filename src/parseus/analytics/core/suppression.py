"""Configurable, per-analytic alert-suppression windows.

An analytic that detects a *standing condition* (an unauthorized user is present,
a function code is anomalous) would otherwise re-alert that same finding on every
scheduled run, burying the one transition that mattered under duplicates. A
**suppression window** turns that repeating condition back into a discrete event:
after a given finding is alerted, re-alerting the *same* finding is suppressed for
a configurable duration.

The window is a single per-analytic value (see :func:`parse_window`):

- ``"0s"`` — never suppress; alert every run the finding is seen (the default, so
  existing analytics are unchanged until an operator opts in);
- a finite duration (``"30m"``, ``"24h"``) — alert, then stay quiet for that long,
  then re-surface if the finding is still present;
- ``"infinite"`` — suppress until the finding stops appearing and returns.

Granularity within an analytic comes from the **finding fingerprint**: the analytic
passes the parts that identify "the same finding" (e.g. a user id, or a
source/dest/protocol/function-code tuple) and the window is applied per distinct
fingerprint. This mirrors the "suppress by field" model used by Elastic Security,
Splunk, and Prometheus Alertmanager.

The window rides on the analytic's :class:`~parseus.analytics.core.state.StateStore`,
so once the runtime persists that state across scheduled runs the suppression
survives restarts.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from parseus.analytics.core.state import StateStore

# Reserved StateStore key under which the fingerprint -> last-emitted-time map is
# stored. Namespaced so it cannot collide with an analytic's own state keys.
_EMISSIONS_KEY = "_suppression_emissions"

# The default window: never suppress. Existing analytics alert every run exactly
# as before until an operator configures a finite window.
DEFAULT_WINDOW = "0s"

# Canonical string an operator/config uses to mean "suppress until the finding
# stops and reappears" (no time-based re-surfacing).
INFINITE = "infinite"

_DURATION_RE = re.compile(r"^\s*(\d+)\s*(s|m|h|d|w)\s*$", re.IGNORECASE)
_UNIT_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 60 * 60,
    "d": 24 * 60 * 60,
    "w": 7 * 24 * 60 * 60,
}


class SuppressionWindowError(ValueError):
    """Raised when a suppression-window value cannot be parsed."""


def parse_window(window: Optional[str]) -> Optional[int]:
    """Parse a suppression-window value into a number of seconds.

    Accepts a Prometheus/Alertmanager-style short-form duration (``"0s"``,
    ``"30m"``, ``"24h"``, ``"7d"``, ``"2w"``), the literal ``"infinite"``, or
    ``None`` (treated as the :data:`DEFAULT_WINDOW`).

    :return: The window as a whole number of seconds; ``0`` means "never
             suppress"; ``None`` means "infinite" (suppress until the finding
             stops appearing and returns).
    :raises SuppressionWindowError: If the value is not a recognised duration.
    """
    if window is None:
        window = DEFAULT_WINDOW
    if not isinstance(window, str):
        raise SuppressionWindowError(
            f"Suppression window must be a string, got {type(window).__name__}."
        )
    text = window.strip().lower()
    if text == INFINITE:
        return None
    match = _DURATION_RE.match(text)
    if not match:
        raise SuppressionWindowError(
            f"Unrecognised suppression window {window!r}; expected a short-form "
            f"duration like '0s', '30m', '24h', or the literal 'infinite'."
        )
    value, unit = match.groups()
    return int(value) * _UNIT_SECONDS[unit.lower()]


def finding_fingerprint(*parts: object) -> str:
    """Return a stable fingerprint identifying a finding from its parts.

    The parts are the fields that make two alerts "the same finding" for
    suppression purposes (the analytic decides which). They are normalised to
    strings and hashed so the fingerprint is a compact, order-sensitive,
    serialisable key. Two calls with equal parts always produce the same
    fingerprint; changing any part (or their order) changes it.
    """
    joined = "\x1f".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


class SuppressionWindow:
    """Decide whether a finding should be emitted or suppressed, backed by state.

    The window reads and records emission times in the analytic's
    :class:`StateStore`, so its decisions persist exactly as far as that state
    does. It is deliberately the single place the "alert every time / suppress
    for N / suppress until it returns" policy lives — analytics call
    :meth:`should_emit` instead of hand-rolling per-finding dedup.
    """

    def __init__(self, state: StateStore, window: Optional[str] = None) -> None:
        """
        :param state: The analytic's run-to-run state store.
        :param window: The configured window (see :func:`parse_window`); defaults
                       to :data:`DEFAULT_WINDOW` ("never suppress").
        """
        self._state = state
        self._window_seconds = parse_window(window)

    def should_emit(self, *fingerprint_parts: object, now: datetime) -> bool:
        """Return whether a finding may be emitted now, recording it if so.

        The finding is identified by ``fingerprint_parts`` (see
        :func:`finding_fingerprint`). The decision:

        - window ``0s`` — always emit (and still record the emission time);
        - window ``infinite`` — emit only if this finding has never been emitted;
        - finite window — emit if never emitted, or if at least the window has
          elapsed since the last emission.

        When this returns ``True`` the current emission time is recorded, so a
        subsequent call for the same finding within the window is suppressed.

        This is the convenience path for the common "one candidate → one gate"
        case. Analytics whose control flow must *check* membership separately
        from *marking* it (e.g. one emitted alert covers several finding keys)
        use :meth:`already_suppressed` and :meth:`record` directly.

        :param fingerprint_parts: The fields identifying "the same finding".
        :param now: The current time (timezone-aware UTC recommended).
        :return: ``True`` to emit the alert, ``False`` to suppress it.
        """
        if self.already_suppressed(*fingerprint_parts, now=now):
            return False
        self.record(*fingerprint_parts, now=now)
        return True

    def already_suppressed(self, *fingerprint_parts: object, now: datetime) -> bool:
        """Return whether this finding is currently suppressed (read-only).

        Unlike :meth:`should_emit`, this never records an emission — it only
        answers "would emitting this finding now be suppressed by an earlier
        emission?". Use it with :meth:`record` when one emitted alert should mark
        several finding keys, or when the check and the mark happen at different
        points in the analytic's control flow.
        """
        fingerprint = finding_fingerprint(*fingerprint_parts)
        emissions = self._state.get(_EMISSIONS_KEY)
        if not emissions:
            return False
        last_iso = emissions.get(fingerprint)
        if last_iso is None:
            return False
        return not self._elapsed(last_iso, now)

    def record(self, *fingerprint_parts: object, now: datetime) -> None:
        """Record that a finding was emitted at ``now`` (starts its window)."""
        fingerprint = finding_fingerprint(*fingerprint_parts)
        emissions = self._state.setdefault(_EMISSIONS_KEY, dict)
        emissions[fingerprint] = now.isoformat()

    def _elapsed(self, last_iso: str, now: datetime) -> bool:
        """Return whether enough time has passed since ``last_iso`` to re-emit."""
        if self._window_seconds is None:
            # Infinite window: once emitted, never re-emit on time alone.
            return False
        if self._window_seconds == 0:
            # Never suppress: the window is always considered elapsed.
            return True
        last = _parse_iso(last_iso)
        if last is None:
            # Unparseable stored timestamp: fail open (emit) rather than hide.
            return True
        return now - last >= timedelta(seconds=self._window_seconds)


def _parse_iso(value: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp, returning ``None`` if it cannot be parsed."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    # Normalise naive timestamps to UTC so comparisons are always valid.
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def window_now(now: Optional[datetime] = None) -> datetime:
    """Coerce a run clock into a timezone-aware UTC datetime for the window.

    Analytics pass their run's ``end`` time as the suppression clock so every
    finding in one run shares a single consistent instant. When ``now`` is
    missing or naive it is normalised to timezone-aware UTC; when it is ``None``
    (e.g. an ad-hoc run without a bound window) the current time is used.
    """
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now
