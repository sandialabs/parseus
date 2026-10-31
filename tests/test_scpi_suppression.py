"""Alert-suppression window tests for the SCPI analytics.

The GPIB listener is a passive, promiscuous bus listener: it stamps a fresh
``@timestamp`` on every distinct payload it receives (see
``parseus.ingestors.gpib.parser``), so routine repeat bus traffic (status
polls, other devices' chatter) keeps producing genuinely new documents even
when nothing operator-relevant changed. Before this fix, ``ScpiValueRangesAnalytic``
and ``ScpiCompareAnalytic`` had no suppression gate, so any run that saw the
same already-reported finding again produced a duplicate alert indefinitely.

These tests pin:
    1. the default ("0s") suppression window alerts every run (unchanged
       behaviour until an operator opts in);
    2. a finite suppression window suppresses a repeat of the *same* finding
       within the window, then re-emits once the window elapses;
    3. a different finding is never suppressed by an unrelated finding's
       window.
"""

from datetime import datetime, timedelta, timezone

from parseus.analytics import ScpiCompareAnalytic, ScpiValueRangesAnalytic
from parseus.analytics.core.state import StateStore

_START = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_END = datetime(2024, 1, 1, 0, 1, 0, tzinfo=timezone.utc)


def _value_ranges_analytic(suppression="0s"):
    analytic = ScpiValueRangesAnalytic(suppression=suppression)
    analytic._fit({"EXAMPLE:COMMAND": {"max": 42, "min": 2}})
    return analytic


def _actions(alerts):
    return [alert["event"]["action"] for alert in alerts]


# ---------------------------------------------------------------------------
# ScpiValueRangesAnalytic
# ---------------------------------------------------------------------------
def test_scpivalueranges_default_suppression_alerts_every_run():
    analytic = _value_ranges_analytic(suppression="0s")
    run_data = {"EXAMPLE:COMMAND": {"max": 43, "min": 2}}
    state = StateStore()

    first = analytic._run(start=_START, end=_END, parsed_run_data=run_data, state=state)
    second = analytic._run(start=_START, end=_END, parsed_run_data=run_data, state=state)

    assert _actions(first) == ["values outside range of training data"]
    assert _actions(second) == ["values outside range of training data"]


def test_scpivalueranges_finite_suppression_suppresses_repeat_then_reemits():
    analytic = _value_ranges_analytic(suppression="24h")
    run_data = {"EXAMPLE:COMMAND": {"max": 43, "min": 2}}
    state = StateStore()

    first = analytic._run(start=_START, end=_END, parsed_run_data=run_data, state=state)
    within = analytic._run(
        start=_START + timedelta(minutes=1),
        end=_END + timedelta(minutes=1),
        parsed_run_data=run_data,
        state=state,
    )
    after = analytic._run(
        start=_START + timedelta(hours=25),
        end=_END + timedelta(hours=25),
        parsed_run_data=run_data,
        state=state,
    )

    assert _actions(first) == ["values outside range of training data"]
    assert _actions(within) == []
    assert _actions(after) == ["values outside range of training data"]


def test_scpivalueranges_suppression_is_per_finding():
    analytic = ScpiValueRangesAnalytic(suppression="24h")
    analytic._fit(
        {
            "EXAMPLE:COMMAND": {"max": 42, "min": 2},
            "EXAMPLE:OTHER": {"max": 42, "min": 2},
        }
    )
    state = StateStore()

    first = analytic._run(
        start=_START,
        end=_END,
        parsed_run_data={"EXAMPLE:COMMAND": {"max": 43, "min": 2}},
        state=state,
    )
    second = analytic._run(
        start=_START + timedelta(minutes=1),
        end=_END + timedelta(minutes=1),
        parsed_run_data={"EXAMPLE:OTHER": {"max": 50, "min": 2}},
        state=state,
    )

    assert _actions(first) == ["values outside range of training data"]
    # A different command/finding is not suppressed by EXAMPLE:COMMAND's window.
    assert _actions(second) == ["values outside range of training data"]


def test_scpivalueranges_snooping_alert_respects_suppression():
    analytic = _value_ranges_analytic(suppression="24h")
    run_data = {"FindLstn": {"value": []}}
    state = StateStore()

    first = analytic._run(start=_START, end=_END, parsed_run_data=run_data, state=state)
    within = analytic._run(
        start=_START + timedelta(minutes=1),
        end=_END + timedelta(minutes=1),
        parsed_run_data=run_data,
        state=state,
    )

    assert "Command found associated with attempting to connect to GPIB listener device" in _actions(
        first
    )
    assert "command not seen in training data" in _actions(first)
    # Both findings for the repeated FindLstn command are suppressed on repeat.
    assert within == []


# ---------------------------------------------------------------------------
# ScpiCompareAnalytic
# ---------------------------------------------------------------------------
def _compare_analytic(suppression="0s"):
    analytic = ScpiCompareAnalytic(suppression=suppression)
    analytic._fit(
        [{"func_code": "KNOWN_CODE", "@timestamp": _START}],
    )
    return analytic


def test_scpicompare_default_suppression_alerts_every_run():
    analytic = _compare_analytic(suppression="0s")
    run_docs = [{"func_code": "NEW_CODE", "@timestamp": _END}]
    state = StateStore()

    first = analytic._run(start=_START, end=_END, run_docs=run_docs, state=state)
    second = analytic._run(start=_START, end=_END, run_docs=run_docs, state=state)

    assert "Value Added" in _actions(first)
    assert "Value Added" in _actions(second)


def test_scpicompare_finite_suppression_suppresses_repeat_then_reemits():
    analytic = _compare_analytic(suppression="24h")
    run_docs = [{"func_code": "NEW_CODE", "@timestamp": _END}]
    state = StateStore()

    first = analytic._run(start=_START, end=_END, run_docs=run_docs, state=state)
    within = analytic._run(
        start=_START + timedelta(minutes=1),
        end=_END + timedelta(minutes=1),
        run_docs=run_docs,
        state=state,
    )
    after = analytic._run(
        start=_START + timedelta(hours=25),
        end=_END + timedelta(hours=25),
        run_docs=run_docs,
        state=state,
    )

    assert "Value Added" in _actions(first)
    assert _actions(within) == []
    assert "Value Added" in _actions(after)
