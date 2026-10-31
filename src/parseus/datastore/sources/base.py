"""Common contract for analytic data sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable


@dataclass(frozen=True)
class RunWindow:
    """A single run window for an analytic data source."""

    start: datetime | None = None
    end: datetime | None = None


class DataSourceConfigurationError(ValueError):
    """Raised when an analytic data source is misconfigured."""


class AnalyticDataSource(ABC):
    """Base class implemented by all analytic data sources.

    Data sources translate their backing storage into the iterable consumed by
    an analytic. Some sources, such as Elasticsearch/OpenSearch, are
    time-windowed; others, such as PEAT filesystem output, are snapshot based.
    """

    @abstractmethod
    def get_fit_data(self, analytic):
        """Return the data object used to fit ``analytic``."""

    @abstractmethod
    def iter_run_windows(self, analytic) -> Iterable[RunWindow]:
        """Yield one or more run windows for ``analytic``."""

    @abstractmethod
    def get_run_data(self, analytic, window: RunWindow):
        """Return the data object for ``analytic`` and ``window``."""
