"""PEAT device logic-change analytic."""
import json

from deepdiff import DeepDiff

from parseus.analytics.base import Analytic
from parseus.analytics.core import build_ecs_alert
from parseus.analytics.capabilities import (
    PeatFileSource,
    JoblibArtifact,
    Supervised,
)
from parseus.analytics.ot_internals._peat_common import convert_to_df
from parseus.analytics.registry import register_analytic
from parseus.preprocessors.peat_dir import peat_logic_transform
from parseus.preprocessors.transform import compose
from parseus.util.datetime_utils import datetime_parser

@register_analytic(
    key="PeatLogicChangeAnalytic",
    family="ot_internals",
    replace=True,
    data_source=PeatFileSource(),
    training=Supervised(),
    persistence=JoblibArtifact(),
    fit_idx={"index_name": "/opt/data/"},
    run_idx={"index_name": "/opt/data/"},
    out_idx={"index_name": "alerts-peat_logic_change_analytic"},
)
class PeatLogicChangeAnalytic(Analytic):
    """
    ----------------------------------
    # Name: PeatLogicChangeAnalytic
    ----------------------------------
    How: Compares PEAT pull results for changes in device parsed logic

    When: You have run PEAT pull previously and want to identify changes in device logic

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
        self._transform = compose(self._transform, peat_logic_transform)
        self.training_device_logic_ = {}

    @classmethod
    def requires_fit(cls) -> bool:
        """
        True if the analytic must be fit before being used, or False otherwise.
        This may be set to false if the analytic is Fit and saved before hand.
        """
        return True

    def _fit(self, *peat_docs):
        logic = peat_docs[0]
        self.training_device_logic_ = logic

    def _run(self, start, end, peat_docs, state, **other_docs) -> list:
        device_logic = peat_docs

        alerts = []

        for device in device_logic:
            if device not in self.training_device_logic_:
                continue

            logic_diff = json.loads(
                DeepDiff(
                    self.training_device_logic_[device][1],
                    device_logic[device][1],
                    ignore_order=True,
                ).to_json()
            )

            if logic_diff:
                alerts.append(
                    build_ecs_alert(
                        "logic changed on device",
                        f"Device {device} has logic changes: {logic_diff}",
                        3.0,
                        category=["host"],
                        timestamp=datetime_parser(device_logic[device][0]),
                        host={
                            "previous_logic": self.training_device_logic_[device][1],
                            "current_logic": device_logic[device][1],
                            "current_pull": datetime_parser(device_logic[device][0]),
                            "previous_pull": datetime_parser(
                                self.training_device_logic_[device][0]
                            ),
                        },
                    )
                )
        return alerts

    def get_fit_results(self):
        """
        Baseline training information stored for each device detected
        by peat. Devices are identified by PEAT summary identity fields.
        """
        # Display dictionary as table
        # Omit process mem dumps
        training_dicts = [
            {
                "device_id": device[0],
                "@timestamp": datetime_parser(device[1][0]),
                "logic": device[1][1],
            }
            for device in self.training_device_logic_.items()
        ]
        return convert_to_df(training_dicts)
