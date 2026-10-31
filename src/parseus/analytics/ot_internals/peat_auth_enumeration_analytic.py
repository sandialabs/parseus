"""PEAT authentication-enumeration analytic."""



from parseus.analytics.base import Analytic
from parseus.analytics.core import build_ecs_alert, build_ecs_baseline
from parseus.analytics.capabilities import (
    PeatFileSource,
    JoblibArtifact,
    Unsupervised,
)
from parseus.analytics.registry import register_analytic
from parseus.preprocessors.peat_dir import (
    peat_event_transform,
)
from parseus.preprocessors.peat_normalize import (
    event_cause_effect,
    event_is_auth_failure,
    event_timestamp,
)
from parseus.preprocessors.transform import compose
from parseus.util.datetime_utils import datetime_parser


@register_analytic(
    key="PeatAuthEnumerationAnalytic",
    family="ot_internals",
    replace=True,
    data_source=PeatFileSource(),
    training=Unsupervised(),
    persistence=JoblibArtifact(),
    fit_idx={"index_name": "/opt/data/"},
    run_idx={"index_name": "/opt/data/"},
    out_idx={"index_name": "alerts-peat_auth_enumeration_analytic"},
)
class PeatAuthEnumerationAnalytic(Analytic):
    """
    ----------------------------------
    # Name: PeatAuthEnumerationAnalytic
    ----------------------------------
    How: Examines PEAT pull event logs for evidence of brute-force enumeration of authentication credentials

    When: You have run a PEAT pull and want to check for patterns of failed authentications

    Usage: <>

    Mitre-Data-Sources:
        + Asset: Asset Inventory

    Mitre-Techniques:
        + Rogue Master (T0848)

    Purdue-Levels:
        + level-1
        + level-2

    Tags:
        + IP
        + Asset Inventory
    """

    def __init__(self, pull_duration=0, verbose=0, **kwargs):
        super().__init__(verbose=verbose, pull_duration=pull_duration, **kwargs)
        self._transform = compose(self._transform, peat_event_transform)
        self.training_device_events_ = {}

    @classmethod
    def requires_fit(cls) -> bool:
        """
        True if the analytic must be fit before being used, or False otherwise.
        This may be set to false if the analytic is Fit and saved before hand.
        """
        return False

    def _fit(self, *peat_docs):
        events = peat_docs[0]
        self.training_device_events_ = events

    def _run(self, start, end, peat_docs, state, **other_docs) -> list:
        device_events = peat_docs

        alerts = []
        baseline_alerts = []

        for device in device_events:
            baseline_alerts.append(
                build_ecs_baseline(
                    f"Device {device} has event logs: {device_events[device][1]}",
                    category=["host"],
                    timestamp=datetime_parser(device_events[device][0]),
                    host={"events": list(device_events[device][1].items())},
                )
            )

        for device in device_events:
            associated_data = []
            auth_fail_time_diffs = []
            last_auth_fail = None
            for event_log in device_events[device][1]:
                for event in device_events[device][1][event_log]:
                    if event_is_auth_failure(event):
                        event_time = event_timestamp(event)
                        if event_time and last_auth_fail:
                            auth_fail_time_diffs.append(event_time - last_auth_fail)

                        if event_time:
                            last_auth_fail = event_time

                        cause_effect = event_cause_effect(event)
                        if cause_effect and cause_effect not in associated_data:
                            associated_data.append(cause_effect)

                short_auth_fails = []
                for auth_fail_time_diff in auth_fail_time_diffs:
                    if auth_fail_time_diff.total_seconds() < 5:
                        short_auth_fails.append(auth_fail_time_diff.total_seconds())

                if len(short_auth_fails) >= 10:
                    alerts.append(
                        build_ecs_alert(
                            "possible auth credential enumeration on device",
                            f"Device {device} has potential brute-force authentication enumeration ({len(auth_fail_time_diffs)} failures)",
                            3.0,
                            category=["host"],
                            timestamp=datetime_parser(device_events[device][0]),
                            host={
                                "authentication_failures_info": associated_data,
                                "authentication_failures_count": len(short_auth_fails),
                                "authentication_failures_avg_resubmit": sum(
                                    short_auth_fails
                                )
                                / len(short_auth_fails),
                                "current_pull": datetime_parser(
                                    device_events[device][0]
                                ),
                            },
                        )
                    )

        alerts += baseline_alerts
        return alerts
