"""PEAT device firmware-change analytic."""

from parseus.analytics.base import Analytic
from parseus.analytics.core import build_ecs_alert
from parseus.analytics.capabilities import (
    PeatFileSource,
    JoblibArtifact,
    Supervised,
)
from parseus.analytics.ot_internals._peat_common import convert_to_df
from parseus.analytics.registry import register_analytic
from parseus.preprocessors.peat_dir import (
    peat_firmware_transform,
)
from parseus.preprocessors.peat_normalize import (
    firmware_version_label,
)
from parseus.preprocessors.transform import compose
from parseus.util.datetime_utils import datetime_parser


@register_analytic(
    key="PeatFirmwareChangeAnalytic",
    family="ot_internals",
    replace=True,
    data_source=PeatFileSource(),
    training=Supervised(),
    persistence=JoblibArtifact(),
    fit_idx={"index_name": "/opt/data/"},
    run_idx={"index_name": "/opt/data/"},
    out_idx={"index_name": "alerts-peat_firmware_change_analytic"},
)
class PeatFirmwareChangeAnalytic(Analytic):
    """
    ----------------------------------
    # Name: PeatFirmwareChangeAnalytic
    ----------------------------------
    How: Compares PEAT pull results for changes to firmware upgrade logs

    When: You have run PEAT pull previously and want to identify reported upgrades to the device firmware

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
        self._transform = compose(self._transform, peat_firmware_transform)
        self.training_device_firmware_ = {}

    @classmethod
    def requires_fit(cls) -> bool:
        """
        True if the analytic must be fit before being used, or False otherwise.
        This may be set to false if the analytic is Fit and saved before hand.
        """
        return True

    def _fit(self, *peat_docs):
        firmware = peat_docs[0]
        self.training_device_firmware_ = firmware

    def _run(self, start, end, peat_docs, state, **other_docs) -> list:
        device_firmware = peat_docs

        alerts = []

        for device in device_firmware:
            if device not in self.training_device_firmware_:
                continue

            firmware_updates = []
            firmware_versions = []

            for firmware_update_logs in device_firmware[device][1]:
                if (
                    firmware_update_logs
                    not in self.training_device_firmware_[device][1]
                ):
                    continue

                for firmware_update in device_firmware[device][1][firmware_update_logs]:
                    if (
                        firmware_update
                        not in self.training_device_firmware_[device][1][
                            firmware_update_logs
                        ]
                    ):
                        firmware_updates.append(firmware_update)
                        firmware_versions.append(
                            firmware_version_label(firmware_update)
                        )

                if firmware_updates:
                    alerts.append(
                        build_ecs_alert(
                            "firmware updated on device",
                            f"Device {device} has firmware updates: versions {firmware_versions}",
                            3.0,
                            category=["host"],
                            timestamp=datetime_parser(device_firmware[device][0]),
                            host={
                                "firmware_updates": firmware_updates,
                                "current_pull": datetime_parser(
                                    device_firmware[device][0]
                                ),
                                "previous_pull": datetime_parser(
                                    self.training_device_firmware_[device][0]
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
                "firmware_updates": list(device[1][1].items()),
            }
            for device in self.training_device_firmware_.items()
        ]
        return convert_to_df(training_dicts)
