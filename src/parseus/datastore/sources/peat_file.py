"""PEAT filesystem analytic data source."""

from __future__ import annotations

import logging
from typing import Callable, Iterable

from .base import AnalyticDataSource, DataSourceConfigurationError, RunWindow

LOGGER = logging.getLogger("parseus.datastore.sources.peat_file")


class PeatFileDataSource(AnalyticDataSource):
    """Snapshot data source for analytics backed by PEAT filesystem output."""

    def __init__(self, analytic_config, *, get_peat_data: Callable) -> None:
        self.config = analytic_config
        self._get_peat_data = get_peat_data

    def _config_value(self, name: str, default=None):
        """Return an optional config value with a default for test/user configs."""
        return getattr(self.config, name, default)

    @staticmethod
    def _require_path(path, purpose: str):
        if not path:
            raise DataSourceConfigurationError(
                f"PeatFileData {purpose} requires a path."
            )
        return path

    def get_fit_data(self, analytic):  # noqa: ARG002
        """Return PEAT filesystem data for fitting an analytic."""
        path = self._require_path(self._config_value("fit_idx"), "fit data")
        return self._get_peat_data(path)

    def iter_run_windows(self, analytic) -> Iterable[RunWindow]:  # noqa: ARG002
        """Yield the single snapshot window used by PEAT filesystem analytics."""
        if self._config_value("schedule", 0):
            LOGGER.warning(
                "Ignoring schedule=%s for PEAT filesystem analytics; "
                "PEAT file data is snapshot based.",
                self._config_value("schedule"),
            )
        yield RunWindow(start=None, end=None)

    def get_run_data(self, analytic, window: RunWindow):  # noqa: ARG002
        """Return PEAT filesystem data for running an analytic."""
        path = self._require_path(self._config_value("run_idx"), "run data")
        return self._get_peat_data(path)
