"""PEAT device process-change analytic."""

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
    peat_process_transform,
)
from parseus.preprocessors.transform import compose

@register_analytic(
    key="PeatProcessChangeAnalytic",
    family="ot_internals",
    replace=True,
    data_source=PeatFileSource(),
    training=Supervised(),
    persistence=JoblibArtifact(),
    fit_idx={"index_name": "/opt/data/"},
    run_idx={"index_name": "/opt/data/"},
    out_idx={"index_name": "alerts-peat_process_change_analytic"},
)
class PeatProcessChangeAnalytic(Analytic):
    """
    ----------------------------------
    # Name: PeatProcessChangeAnalytic
    ----------------------------------
    How: Compares PEAT result directories for changes in the set of process names on a device

    When: You have run PEAT pull previously and want to identify changes in the set of process names on a device (process memory dumps are not compared)

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
        self._transform = compose(self._transform, peat_process_transform)
        self.training_device_processes_ = {}

    @classmethod
    def requires_fit(cls) -> bool:
        """
        True if the analytic must be fit before being used, or False otherwise.
        This may be set to false if the analytic is Fit and saved before hand.
        """
        return True

    def _fit(self, *peat_docs):
        processes = peat_docs[0]
        self.training_device_processes_ = processes

    def _run(self, start, end, peat_docs, state, **other_docs) -> list:
        device_processes = peat_docs

        alerts = []

        for device in device_processes:
            if device not in self.training_device_processes_:
                continue
            diff_processes_added = []
            diff_processes_removed = []

            for process_name in device_processes[device][1]:
                if process_name not in self.training_device_processes_[device][1]:
                    diff_processes_added.append(process_name)

            for process_name in self.training_device_processes_[device][1]:
                if process_name not in device_processes[device][1]:
                    diff_processes_removed.append(process_name)

            if diff_processes_added or diff_processes_removed:
                alerts.append(
                    build_ecs_alert(
                        "process changed on device",
                        f"Device {device} has changed processes: {diff_processes_added} were added, {diff_processes_removed} were removed",
                        3.0,
                        category=["host"],
                        timestamp=datetime_parser(device_processes[device][0]),
                        host={
                            "processes_added": diff_processes_added,
                            "processes_removed": diff_processes_removed,
                            "current_pull": datetime_parser(
                                device_processes[device][0]
                            ),
                            "previous_pull": datetime_parser(
                                self.training_device_processes_[device][0]
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
                "processes": list(device[1][1]),
            }
            for device in self.training_device_processes_.items()
        ]
        return convert_to_df(training_dicts)
