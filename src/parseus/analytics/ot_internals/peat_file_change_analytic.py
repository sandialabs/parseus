"""PEAT device file-change analytic."""

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
    peat_file_transform,
)
from parseus.preprocessors.transform import compose


@register_analytic(
    key="PeatFileChangeAnalytic",
    family="ot_internals",
    replace=True,
    data_source=PeatFileSource(),
    training=Supervised(),
    persistence=JoblibArtifact(),
    fit_idx={"index_name": "/opt/data/"},
    run_idx={"index_name": "/opt/data/"},
    out_idx={"index_name": "alerts-peat_file_change_analytic"},
)
class PeatFileChangeAnalytic(Analytic):
    """
    ----------------------------------
    # Name: PeatFileChangeAnalytic
    ----------------------------------
    How: Compares PEAT result directories for changes in the set of file names on a device

    When: You have run PEAT pull previously and want to identify changes in the set of files on a device

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
        self._transform = compose(self._transform, peat_file_transform)
        self.training_device_files_ = {}

    @classmethod
    def requires_fit(cls) -> bool:
        """
        True if the analytic must be fit before being used, or False otherwise.
        This may be set to false if the analytic is Fit and saved before hand.
        """
        return True

    def _fit(self, *peat_docs):
        # peat_docs: {device_id: (timestamp, set(files))}
        device_files = peat_docs[0]
        self.training_device_files_ = device_files

    def _run(self, start, end, peat_docs, state, **other_docs) -> list:
        # peat_docs: {device_id: (timestamp, set(files))}
        device_files = peat_docs
        alerts = []

        for device in device_files:
            if device not in self.training_device_files_:
                continue
            # Alert on set of files being changed
            diff_files_added = device_files[device][1].difference(
                self.training_device_files_[device][1]
            )
            diff_files_removed = self.training_device_files_[device][1].difference(
                device_files[device][1]
            )

            if diff_files_added or diff_files_removed:
                alerts.append(
                    build_ecs_alert(
                        "file changed on device",
                        f"Device {device} has changed files: {diff_files_added} were added, {diff_files_removed} were removed",
                        3.0,
                        category=["host"],
                        timestamp=datetime_parser(device_files[device][0]),
                        host={
                            "files_added": list(diff_files_added),
                            "files_removed": list(diff_files_removed),
                            "current_pull": datetime_parser(device_files[device][0]),
                            "previous_pull": datetime_parser(
                                self.training_device_files_[device][0]
                            ),
                        },
                    )
                )

        # TODO diff file contents
        # TODO run strings on diff file contents
        return alerts

    def get_fit_results(self):
        """
        Baseline training information stored for each device detected
        by peat. Devices are identified by PEAT summary identity fields.
        """
        # Display dictionary as table
        training_dicts = [
            {
                "device_id": device[0],
                "@timestamp": datetime_parser(device[1][0]),
                "files": list(device[1][1]),
            }
            for device in self.training_device_files_.items()
        ]
        return convert_to_df(training_dicts)
