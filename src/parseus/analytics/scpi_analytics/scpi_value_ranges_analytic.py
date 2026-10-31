"""
Analytic for SCPI data
Looks for changes in SCPI command argument values.
"""

from parseus.analytics.base import Analytic
from parseus.analytics.core import build_ecs_alert
from parseus.analytics.core.suppression import SuppressionWindow, window_now
from parseus.analytics.capabilities import (
    ElasticsearchSource,
    JoblibArtifact,
    Supervised,
)
from parseus.analytics.registry import register_analytic
from parseus.analytics.scpi_analytics.scpi_transform import scpi_transform


@register_analytic(
    key="ScpiValueRangesAnalytic",
    family="scpi_analytics",
    replace=True,
    data_source=ElasticsearchSource(),
    training=Supervised(),
    persistence=JoblibArtifact(),
    fit_idx={
        "index_name": "ground_truth*",
        "start": "2025-07-01T00:00:00Z",
        "end": "2025-07-15T00:00:00Z",
    },
    run_idx={
        "index_name": "scpi_parsed*",
        "start": "2025-07-16T00:00:00Z",
    },
    out_idx={"index_name": "alerts-scpi_analytic"},
)
class ScpiValueRangesAnalytic(Analytic):
    """
    Name: ScpiValueRangesAnalytic

    How: Analytic that compares the values of each command argument in SCPI
         communication against the ranges of values in the training dataset.

    When: Detect end device or SCPI communication that might be compromised.

    Mitre-Data-Sources:
        + Network Traffic: Network Traffic Content

    Mitre-Techniques:
        + impair-process-control (TA0106)
        + inhibit-response-function (TA0107)
        + command-and-control (TA0101)
        + Command: Command Execution
        + Device Restart/Shutdown (T0816)
        + Change Operating Mode (T0858)
        + Change Program State (T0875)
        + Rogue Master (T0848)

    Purdue-Levels:
        + level 1
    """

    def __init__(self, pull_duration=0, **kwargs):
        super().__init__(pull_duration=pull_duration, **kwargs)
        self._transform = scpi_transform
        self.fit_results_doc = "Baseline SCPI command argument value ranges."
        self.run_results_doc = (
            "Alerts when SCPI command argument values fall outside the baseline "
            "ranges, use unfamiliar channels, or use unfamiliar values/labels."
        )
        self.groundtruth_value_ranges_ = {}

    def _fit(self, value_ranges):
        self.groundtruth_value_ranges_ = value_ranges
        return value_ranges

    def get_fit_results(self):
        return self.groundtruth_value_ranges_

    def _run(self, start, end, parsed_run_data, state, **additional_args):
        """
        Compare commands and their arguments in run data to groundtruth data and ensure values
        are in an expected range/channel

        SCPI command args can include a value (float type), a string literal (ON/OFF/METERXYZ),
            and/or a channel (@1, etc)
        SCPI command args are organizes into a dict: command: {max: x, min: y, channel: z,
            str literal (ie METERXYZ), values: [ON/OFF], subcommand: {}}

        Each distinct (command, alert_type) finding is gated by an alert-suppression
        window: the GPIB listener is a passive, promiscuous bus listener, so routine
        repeat traffic (status polls, other devices' chatter) keeps producing
        genuinely new documents even when nothing operator-relevant changed. Without
        suppression this re-alerts the same already-reported finding on every run that
        happens to see it again. The default suppression window ("0s") never
        suppresses, so behaviour is unchanged until an operator configures a window.

        Args:
            start: start time for gathering run data from elastic, a datetime object or None
            end: end time for gathering run data from elastic, a datetime object or None
            parsed_run_data: command => parsed-argument dict for this run window,
                produced by scpi_transform() from the ES docs containing SCPI commands
            **additional_args: not currently used, but additional args data can be put here in future
        """
        suppression = SuppressionWindow(state, self.suppression_)
        now = window_now(end)
        alerts = []
        for command in parsed_run_data:
            if ("FindLstn" in command) or ("*IDN" in command):
                alert_type = (
                    "Command found associated with attempting to"
                    " connect to GPIB listener device"
                )
                if suppression.should_emit(command, alert_type, now=now):
                    snooping_alert = build_alert(
                        alert_value=command,
                        timestamp=end,
                        alert_type=alert_type,
                        command=command,
                    )
                    alerts.append(snooping_alert)
            try:
                fit_args = self.groundtruth_value_ranges_[command]
                run_args = parsed_run_data[command]
            except KeyError:
                alert_type = "command not seen in training data"
                if suppression.should_emit(command, alert_type, now=now):
                    alert = build_alert(
                        alert_value=command,
                        timestamp=end,
                        alert_type=alert_type,
                        command=command,
                    )
                    alerts.append(alert)
                continue
            command_alerts = find_command_alerts(
                command, run_args, fit_args, end, suppression=suppression, now=now
            )
            alerts.extend(command_alerts)
        return alerts


def find_command_alerts(
    command, run_arguments, fit_arguments, timestamp, suppression=None, now=None
):
    alerts = []
    if values_out_of_range(run_arguments, fit_arguments):
        alert_type = "values outside range of training data"
        if suppression is None or suppression.should_emit(
            command, alert_type, now=now
        ):
            alert = build_alert(
                alert_value=run_arguments,
                timestamp=timestamp,
                alert_type=alert_type,
                command=command,
            )
            alerts.append(alert)
    if unfamilar_channel(run_arguments, fit_arguments):
        alert_type = "unfamliar channel used"
        if suppression is None or suppression.should_emit(
            command, alert_type, now=now
        ):
            channel_list = [
                x
                for x in run_arguments["channels"]
                if x not in fit_arguments["channels"]
            ]
            alert = build_alert(
                alert_value=channel_list,
                timestamp=timestamp,
                alert_type=alert_type,
                command=command,
            )
            alerts.append(alert)
    if unfamiliar_value(run_arguments, fit_arguments):
        alert_type = "unfamliar value found"
        if suppression is None or suppression.should_emit(
            command, alert_type, now=now
        ):
            alert = build_alert(
                alert_value=[
                    x for x in run_arguments["value"] if x not in fit_arguments["value"]
                ],
                timestamp=timestamp,
                alert_type=alert_type,
                command=command,
            )
            alerts.append(alert)
    if unfamiliar_label(run_arguments, fit_arguments):
        alert_type = "unfamliar label found"
        if suppression is None or suppression.should_emit(
            command, alert_type, now=now
        ):
            alert = build_alert(
                alert_value=[x for x in run_arguments if x not in fit_arguments],
                timestamp=timestamp,
                alert_type=alert_type,
                command=command,
            )
            alerts.append(alert)
    return alerts


def unfamilar_channel(run_arguments, fit_arguments):
    return "channels" in run_arguments and not run_arguments["channels"].issubset(
        fit_arguments["channels"]
    )


def values_out_of_range(run_arguments, fit_arguments):
    return (
        "min" in run_arguments
        and "max" in run_arguments
        and (
            run_arguments["max"] > fit_arguments["max"]
            or run_arguments["min"] < fit_arguments["min"]
        )
    )


def unfamiliar_value(run_arguments, fit_arguments):
    return "value" in run_arguments and set(run_arguments["value"]) != set(
        fit_arguments["value"]
    )


def unfamiliar_label(run_arguments, fit_arguments):
    return isinstance(run_arguments, set) and run_arguments != fit_arguments


def build_alert(alert_value, timestamp, alert_type, command=""):
    return build_ecs_alert(
        action=alert_type,
        original=f"Detected {alert_type}: {alert_value}",
        riskscore=5.0,
        category="network",
        timestamp=timestamp,
        event_extra={"command": command},
        handled=False,
    )
