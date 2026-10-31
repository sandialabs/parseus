from datetime import datetime, timedelta

import pandas as pd

from parseus.analytics.ot_network.ot_function_code_anomaly_analytic import (
    OTFunctionCodeAnomalyAnalytic,
)


_START = datetime(2024, 1, 1, 0, 0, 0)
_END = datetime(2024, 1, 1, 1, 0, 0)


class FakeFunctionCodeLogic:
    def __init__(self, baseline_keys):
        self.stats_df = pd.DataFrame(
            {
                "mean": [1.0 for _ in baseline_keys],
                "std": [1.0 for _ in baseline_keys],
            },
            index=baseline_keys,
        )

    def run_table(self, *_args, **_kwargs):
        # No increased-rate alerts for these tests.
        dataset = _args[1]
        return None, pd.DataFrame(index=dataset.index)


def _analytic(suppression="0s", baseline_keys=None):
    analytic = OTFunctionCodeAnomalyAnalytic(suppression=suppression)
    analytic.logic_ = FakeFunctionCodeLogic(baseline_keys or [])
    return analytic


def _alert_originals(docs):
    return [
        doc.get("event", {}).get("original", "")
        for doc in docs
        if doc.get("event", {}).get("kind") == "alert"
    ]


def test_ot_function_code_default_suppression_alerts_every_run():
    key = "10.0.0.1_10.0.0.2:modbus:new_code"

    analytic = _analytic(
        suppression="0s",
        baseline_keys=["10.0.0.1_10.0.0.2:modbus:known_code"],
    )

    dataset = pd.DataFrame(
        {key: [1]},
        index=[_END],
    )

    first = analytic._run(_START, _END, dataset, analytic._state)
    second = analytic._run(_START, _END, dataset, analytic._state)

    assert any("New Function Codes" in text for text in _alert_originals(first))
    assert any("New Function Codes" in text for text in _alert_originals(second))


def test_ot_function_code_finite_suppression_suppresses_then_reemits():
    key = "10.0.0.1_10.0.0.2:modbus:new_code"

    analytic = _analytic(
        suppression="24h",
        baseline_keys=["10.0.0.1_10.0.0.2:modbus:known_code"],
    )

    dataset = pd.DataFrame(
        {key: [1]},
        index=[_END],
    )

    first = analytic._run(_START, _END, dataset, analytic._state)
    within = analytic._run(
        _START + timedelta(hours=1),
        _END + timedelta(hours=1),
        dataset,
        analytic._state,
    )
    after = analytic._run(
        _START + timedelta(hours=25),
        _END + timedelta(hours=25),
        dataset,
        analytic._state,
    )

    assert any("New Function Codes" in text for text in _alert_originals(first))
    assert not any("New Function Codes" in text for text in _alert_originals(within))
    assert any("New Function Codes" in text for text in _alert_originals(after))


def test_ot_function_code_enumeration_covers_individual_new_code_alerts_this_run():
    ips_protocol = "10.0.0.1_10.0.0.2:modbus"
    keys = [f"{ips_protocol}:new_code_{i}" for i in range(10)]

    analytic = _analytic(
        suppression="0s",
        baseline_keys=[],
    )

    dataset = pd.DataFrame(
        {key: [1] for key in keys},
        index=[_END],
    )

    alerts = analytic._run(_START, _END, dataset, analytic._state)
    originals = _alert_originals(alerts)

    enumeration_alerts = [
        text for text in originals
        if "Possible Function Code Enumeration" in text
    ]
    individual_new_code_alerts = [
        text for text in originals
        if "New Function Codes" in text
    ]

    assert len(enumeration_alerts) == 1
    assert individual_new_code_alerts == []


def test_ot_function_code_dos_alert_covers_same_key_this_run():
    key = "10.0.0.1_10.0.0.2:modbus:cold restart"

    analytic = _analytic(
        suppression="0s",
        baseline_keys=[],
    )

    dataset = pd.DataFrame(
        {key: [30]},
        index=[_END],
    )

    alerts = analytic._run(_START, _END, dataset, analytic._state)
    originals = _alert_originals(alerts)

    assert any("Possible Denial-Of-Service" in text for text in originals)
    assert not any("New Function Codes" in text for text in originals)
