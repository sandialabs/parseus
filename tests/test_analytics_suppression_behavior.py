"""Behavioural tests for suppression windows wired into real analytics.

These complement the engine-core unit tests in ``test_analytics_suppression``
and the parity checks in ``test_analytics_state_contract``: they prove the
*new capability* works end-to-end through an analytic's ``run_on_data`` —

    1. the default "0s" window is unchanged (alerts every run);
    2. a finite window suppresses repeats of the same finding within the window
       and re-alerts once it elapses;
    3. suppression is per finding (one IP's window does not mute another's).

The Sysmon unapproved-IP analytic is used because it is unsupervised and emits
one alert per unfamiliar value, making the suppression effect directly
observable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from parseus.analytics.host_anomalies.sysmon_unapproved_ip_analytic import (
    SysmonUnapprovedIpAnalytic,
)

_T0 = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _doc(ip: str, ts: str = "2024-01-01T00:00:01Z") -> dict:
    return {"@timestamp": ts, "winlog": {"event_data": {"SourceAddress": ip}}}


def _alerting_ips(alerts) -> list[str]:
    return sorted(a["source"]["ip"] for a in alerts if "source" in a)


def test_default_window_alerts_every_run():
    # Default suppression "0s": the same IP alerts on every run (unchanged).
    # Isolate the analytic's own "learned good IP" list so only the (default)
    # window governs output — otherwise run 1 would mark the IP known-good.
    analytic = SysmonUnapprovedIpAnalytic(known_good_ips=[])
    analytic.known_good_ips_ = _NeverContains()
    docs = [_doc("192.0.2.10")]

    first = analytic.run_on_data(docs, start=_T0, end=_T0)
    second = analytic.run_on_data(docs, start=_T0, end=_T0 + timedelta(minutes=5))

    assert _alerting_ips(first) == ["192.0.2.10"]
    assert _alerting_ips(second) == ["192.0.2.10"]


def test_finite_window_suppresses_repeat_then_reemits():
    # A 24h window: the same IP alerts once, stays quiet within 24h, re-alerts
    # after. known_good_ips is disabled here so only the window governs output.
    analytic = SysmonUnapprovedIpAnalytic(known_good_ips=[], suppression="24h")
    # Stop the analytic's own "learned good IP" list from masking the effect.
    analytic.known_good_ips_ = _NeverContains()
    docs = [_doc("192.0.2.10")]

    first = analytic.run_on_data(docs, start=_T0, end=_T0)
    within = analytic.run_on_data(docs, start=_T0, end=_T0 + timedelta(hours=1))
    after = analytic.run_on_data(docs, start=_T0, end=_T0 + timedelta(hours=25))

    assert _alerting_ips(first) == ["192.0.2.10"]
    assert _alerting_ips(within) == []  # suppressed within the window
    assert _alerting_ips(after) == ["192.0.2.10"]  # re-alerts after it elapses


def test_finite_window_is_per_finding():
    analytic = SysmonUnapprovedIpAnalytic(known_good_ips=[], suppression="24h")
    analytic.known_good_ips_ = _NeverContains()

    first = analytic.run_on_data([_doc("192.0.2.10")], start=_T0, end=_T0)
    # A different IP one minute later is unaffected by the first IP's window.
    other = analytic.run_on_data(
        [_doc("192.0.2.11")], start=_T0, end=_T0 + timedelta(minutes=1)
    )

    assert _alerting_ips(first) == ["192.0.2.10"]
    assert _alerting_ips(other) == ["192.0.2.11"]


class _NeverContains:
    """A list-like that never reports membership and ignores extend().

    Lets a test isolate the suppression window from the analytic's own
    "already-seen good value" allow-list, which would otherwise mute the second
    run before the window is even consulted. It iterates as empty so
    ``set(known_good_ips or [])`` inside the analytic yields an empty set.
    """

    def __contains__(self, _item) -> bool:
        return False

    def __iter__(self):
        return iter(())

    def __bool__(self) -> bool:
        return True

    def extend(self, _items) -> None:
        pass
