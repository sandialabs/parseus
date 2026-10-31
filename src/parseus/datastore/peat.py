"""Filesystem reader for PEAT run output."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from parseus.util.datetime_utils import datetime_parser

LOGGER = logging.getLogger("parseus.datastore.peat")


@dataclass(frozen=True)
class PeatDeviceDocument:
    """Normalized handle for a single device in PEAT filesystem output."""

    path: Path
    timestamp: float
    device_id: str
    summary: dict[str, Any] = field(default_factory=dict)


class PeatDocumentData:
    """Iterable PEAT filesystem data source for one PEAT run directory."""

    SUMMARY_FILENAME = "device-data-summary.json"

    def __init__(self, directory_path: str | Path):
        self.directory_path = Path(directory_path).expanduser().resolve()
        self.devices = self._discover_devices()

    def __iter__(self):
        yield from sorted(self.devices, key=lambda device: device.device_id)

    def __len__(self) -> int:
        return len(self.devices)

    def __getitem__(self, item):
        return self.devices[item]

    @staticmethod
    def _device_id_from_summary(summary: dict[str, Any]) -> str | None:
        """Return a stable device identifier from PEAT summary content."""
        for key in ("id", "label", "ip", "hostname", "name", "mac", "serial_port"):
            value = summary.get(key)
            if value:
                return str(value)

        related = summary.get("related") or {}
        related_ips = related.get("ip") or []
        if isinstance(related_ips, str):
            return related_ips
        if related_ips:
            return str(sorted(str(ip) for ip in related_ips)[0])

        return None

    @staticmethod
    def _timestamp_from_summary(
        summary: dict[str, Any], summary_path: Path, device_path: Path
    ) -> float:
        """Return a PEAT device timestamp without relying on filesystem ctime."""
        for key in ("@timestamp", "timestamp", "created", "start_time"):
            value = summary.get(key)
            if value:
                try:
                    parsed = datetime_parser(value)
                    if isinstance(parsed, datetime):
                        return parsed.timestamp()
                except (TypeError, ValueError):
                    LOGGER.debug(
                        "Unable to parse PEAT timestamp %r from %s", value, key
                    )

        if summary_path.exists():
            return summary_path.stat().st_mtime
        return device_path.stat().st_mtime

    @classmethod
    def _load_summary(cls, device_path: Path) -> dict[str, Any]:
        summary_path = device_path / cls.SUMMARY_FILENAME
        if not summary_path.exists():
            return {}
        try:
            with summary_path.open(encoding="utf-8") as file_obj:
                data = json.load(file_obj)
        except json.JSONDecodeError:
            LOGGER.exception("Invalid PEAT summary JSON: %s", summary_path)
            return {}
        except OSError:
            LOGGER.exception("Unable to read PEAT summary JSON: %s", summary_path)
            return {}
        return data if isinstance(data, dict) else {}

    def _device_paths(self) -> list[Path]:
        """Return PEAT device directories from a run, devices, or single-device path."""
        if not self.directory_path.is_dir():
            raise FileNotFoundError(
                f"PEAT filesystem data path does not exist: {self.directory_path}"
            )

        if (self.directory_path / self.SUMMARY_FILENAME).is_file():
            return [self.directory_path]

        devices_path = self.directory_path / "devices"
        root = devices_path if devices_path.is_dir() else self.directory_path
        device_paths = sorted(
            path
            for path in root.iterdir()
            if path.is_dir() and (path / self.SUMMARY_FILENAME).is_file()
        )
        if not device_paths:
            LOGGER.warning("No PEAT device summaries found in %s", self.directory_path)
        return device_paths

    def _discover_devices(self) -> list[PeatDeviceDocument]:
        """Discover devices from PEAT filesystem output."""
        devices: list[PeatDeviceDocument] = []
        for device_path in self._device_paths():
            summary = self._load_summary(device_path)
            summary_path = device_path / self.SUMMARY_FILENAME
            device_id = self._device_id_from_summary(summary)
            if not device_id:
                LOGGER.warning(
                    "Skipping PEAT device summary without identity: %s",
                    summary_path,
                )
                continue
            devices.append(
                PeatDeviceDocument(
                    path=device_path,
                    timestamp=self._timestamp_from_summary(
                        summary, summary_path, device_path
                    ),
                    device_id=device_id,
                    summary=summary,
                )
            )
        return devices
