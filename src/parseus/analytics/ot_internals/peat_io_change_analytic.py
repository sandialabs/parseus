"""PEAT device I/O module-change analytic."""
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
from parseus.util.datetime_utils import datetime_parser
from parseus.preprocessors.peat_dir import (
    peat_io_transform,
)
from parseus.preprocessors.transform import compose

@register_analytic(
    key="PeatIOChangeAnalytic",
    family="ot_internals",
    replace=True,
    data_source=PeatFileSource(),
    training=Supervised(),
    persistence=JoblibArtifact(),
    fit_idx={"index_name": "/opt/data/"},
    run_idx={"index_name": "/opt/data/"},
    out_idx={"index_name": "alerts-peat_io_change_analytic"},
)
class PeatIOChangeAnalytic(Analytic):
    """
    ----------------------------------
    # Name: PeatIOChangeAnalytic
    ----------------------------------
    How: Compares PEAT pull results for changes in device IO state configuration

    When: You have run PEAT pull previously and want to identify changes in device IO configuration settings

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
        self._transform = compose(self._transform, peat_io_transform)
        self.training_device_io_ = {}

    @classmethod
    def requires_fit(cls) -> bool:
        """
        True if the analytic must be fit before being used, or False otherwise.
        This may be set to false if the analytic is Fit and saved before hand.
        """
        return True

    def _fit(self, *peat_docs):
        io = peat_docs[0]
        self.training_device_io_ = io

    def _run(self, start, end, peat_docs, state, **other_docs) -> list:
        device_io = peat_docs

        alerts = []

        for device in device_io:
            if device not in self.training_device_io_:
                continue
            # Compare io module names, then labels/handles if present in both sets
            diff_io_added = []
            diff_io_removed = []
            io_diffs = []

            for module_type in device_io[device][1]:
                # Analytic ignores changes to entire categories of modules for now (in/out)
                if module_type not in self.training_device_io_[device][1]:
                    continue

                for io_module_name in device_io[device][1][module_type]:
                    if (
                        io_module_name
                        not in self.training_device_io_[device][1][module_type]
                    ):
                        diff_io_added.append(module_type + ": " + io_module_name)
                    else:
                        if (
                            device_io[device][1][module_type][io_module_name]
                            != self.training_device_io_[device][1][module_type][
                                io_module_name
                            ]
                        ):
                            io_diffs.append(
                                (
                                    module_type + ": " + io_module_name,
                                    json.loads(
                                        DeepDiff(
                                            self.training_device_io_[device][1][
                                                module_type
                                            ][io_module_name],
                                            device_io[device][1][module_type][
                                                io_module_name
                                            ],
                                            ignore_order=True,
                                        ).to_json()
                                    ),
                                )
                            )

                for io_module_name in self.training_device_io_[device][1][module_type]:
                    if io_module_name not in device_io[device][1][module_type]:
                        diff_io_removed.append(module_type + ": " + io_module_name)

                if diff_io_added or diff_io_removed or io_diffs:
                    alerts.append(
                        build_ecs_alert(
                            "I/O modules changed on device",
                            f"Device {device} has changed I/O modules: {diff_io_added} were added, {diff_io_removed} were removed, {io_diffs} were changed",
                            3.0,
                            category=["host"],
                            timestamp=datetime_parser(device_io[device][0]),
                            host={
                                "io_modules_added": diff_io_added,
                                "io_modules_removed": diff_io_removed,
                                "io_modules_changed": io_diffs,
                                "current_pull": datetime_parser(device_io[device][0]),
                                "previous_pull": datetime_parser(
                                    self.training_device_io_[device][0]
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
                "io_modules": list(
                    (module_category, device[1][1][module_category])
                    for module_category in device[1][1]
                ),
            }
            for device in self.training_device_io_.items()
        ]
        return convert_to_df(training_dicts)
