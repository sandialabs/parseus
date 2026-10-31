from parseus.analytics import ScpiValueRangesAnalytic
from parseus.analytics.core.state import StateStore


def test_scpivalueranges_analytic_unknown_command():
    transformed_fit_data = {
        "EXAMPLE:COMMAND": {"max": 42, "min": 2},
    }
    analytic_instance = ScpiValueRangesAnalytic()
    analytic_instance._fit(transformed_fit_data)
    transformed_run_data = {
        "EXAMPLE:OTHER_COMMAND": {"max": 43, "min": 2},
    }
    alerts = analytic_instance._run(
        start=None, end=None, parsed_run_data=transformed_run_data, state=StateStore()
    )
    assert alerts == [
        {
            "@timestamp": None,
            "event": {
                "action": "command not seen in training data",
                "category": ["network"],
                "command": "EXAMPLE:OTHER_COMMAND",
                "kind": "alert",
                "original": "Detected command not seen in training data: EXAMPLE:OTHER_COMMAND",
                "riskscore": 5.0,
            },
            "handled": False,
        }
    ]


def test_scpivalueranges_analytic_min_max():
    transformed_fit_data = {
        "EXAMPLE:COMMAND": {"max": 42, "min": 2},
    }
    analytic_instance = ScpiValueRangesAnalytic()
    analytic_instance._fit(transformed_fit_data)
    transformed_run_data = {
        "EXAMPLE:COMMAND": {"max": 43, "min": 2},
    }
    alerts = analytic_instance._run(
        start=None, end=None, parsed_run_data=transformed_run_data, state=StateStore()
    )
    assert alerts == [
        {
            "@timestamp": None,
            "event": {
                "action": "values outside range of training data",
                "category": ["network"],
                "command": "EXAMPLE:COMMAND",
                "kind": "alert",
                "original": "Detected values outside range of training data: {'max': 43, 'min': 2}",
                "riskscore": 5.0,
            },
            "handled": False,
        }
    ]
    transformed_fit_data = {
        "EXAMPLE:COMMAND": {"max": 42, "min": 2},
    }
    analytic_instance = ScpiValueRangesAnalytic()
    analytic_instance._fit(transformed_fit_data)
    transformed_run_data = {
        "EXAMPLE:COMMAND": {"max": 42, "min": -10},
    }
    alerts = analytic_instance._run(
        start=None, end=None, parsed_run_data=transformed_run_data, state=StateStore()
    )
    assert alerts == [
        {
            "@timestamp": None,
            "event": {
                "action": "values outside range of training data",
                "category": ["network"],
                "command": "EXAMPLE:COMMAND",
                "kind": "alert",
                "original": "Detected values outside range of training data: {'max': 42, 'min': -10}",
                "riskscore": 5.0,
            },
            "handled": False,
        }
    ]


def test_scpivalueranges_analytic_unfamiliar_channel():
    transformed_fit_data = {
        "EXAMPLE:COMMAND": {"max": 42, "min": 2, "channels": {1, 2, 3}},
    }
    analytic_instance = ScpiValueRangesAnalytic()
    analytic_instance._fit(transformed_fit_data)
    transformed_run_data = {
        "EXAMPLE:COMMAND": {"max": 42, "min": 2, "channels": {4, 5, 6}},
    }
    alerts = analytic_instance._run(
        start=None, end=None, parsed_run_data=transformed_run_data, state=StateStore()
    )
    assert alerts == [
        {
            "@timestamp": None,
            "event": {
                "action": "unfamliar channel used",
                "category": ["network"],
                "command": "EXAMPLE:COMMAND",
                "kind": "alert",
                "original": "Detected unfamliar channel used: [4, 5, 6]",
                "riskscore": 5.0,
            },
            "handled": False,
        }
    ]


def test_scpivalueranges_analytic_unfamiliar_value():
    transformed_fit_data = {
        "EXAMPLE:COMMAND": {"value": ["ON", "OFF"]},
    }
    analytic_instance = ScpiValueRangesAnalytic()
    analytic_instance._fit(transformed_fit_data)
    transformed_run_data = {
        "EXAMPLE:COMMAND": {"value": ["ON", "OFF", "TEST"]},
    }
    alerts = analytic_instance._run(
        start=None, end=None, parsed_run_data=transformed_run_data, state=StateStore()
    )
    assert alerts == [
        {
            "@timestamp": None,
            "event": {
                "action": "unfamliar value found",
                "category": ["network"],
                "command": "EXAMPLE:COMMAND",
                "kind": "alert",
                "original": "Detected unfamliar value found: ['TEST']",
                "riskscore": 5.0,
            },
            "handled": False,
        }
    ]


def test_scpivalueranges_analytic_detect_gpib_snooping():
    transformed_fit_data = {
        "EXAMPLE:COMMAND": {"value": ["ON", "OFF"]},
    }
    analytic_instance = ScpiValueRangesAnalytic()
    analytic_instance._fit(transformed_fit_data)
    transformed_run_data = {"FindLstn": {"value": []}, "*IDN": {"value": []}}
    alerts = analytic_instance._run(
        start=None, end=None, parsed_run_data=transformed_run_data, state=StateStore()
    )
    assert alerts == [
        {
            "@timestamp": None,
            "event": {
                "action": "Command found associated with attempting to connect to "
                "GPIB listener device",
                "category": ["network"],
                "command": "FindLstn",
                "kind": "alert",
                "original": "Detected Command found associated with attempting to "
                "connect to GPIB listener device: FindLstn",
                "riskscore": 5.0,
            },
            "handled": False,
        },
        {
            "@timestamp": None,
            "event": {
                "action": "command not seen in training data",
                "category": ["network"],
                "command": "FindLstn",
                "kind": "alert",
                "original": "Detected command not seen in training data: FindLstn",
                "riskscore": 5.0,
            },
            "handled": False,
        },
        {
            "@timestamp": None,
            "event": {
                "action": "Command found associated with attempting to connect to "
                "GPIB listener device",
                "category": ["network"],
                "command": "*IDN",
                "kind": "alert",
                "original": "Detected Command found associated with attempting to "
                "connect to GPIB listener device: *IDN",
                "riskscore": 5.0,
            },
            "handled": False,
        },
        {
            "@timestamp": None,
            "event": {
                "action": "command not seen in training data",
                "category": ["network"],
                "command": "*IDN",
                "kind": "alert",
                "original": "Detected command not seen in training data: *IDN",
                "riskscore": 5.0,
            },
            "handled": False,
        },
    ]
