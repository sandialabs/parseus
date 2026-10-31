"""Registry of webapp data-source providers for analytics.

An analytic runs against data produced by *some* source: an Elasticsearch /
OpenSearch index, or the filesystem output of a PEAT run, etc. The analytics
engine (``parseus.datastore.sources``) is already generic -- it takes a resolved
index name or filesystem path. What the *webapp* needs is a pluggable seam so
that:

* the app that owns a data source (e.g. ``pei`` for PEAT output) can advertise
  how to list available datasets and how to turn a chosen dataset id into the
  concrete index/path the engine consumes, and
* the ``analytics`` app can consume those providers generically, without
  importing another app's settings or URLs.

A :class:`DataSourceProvider` is registered by an app in its
``AppConfig.ready``. If the owning app is not installed, no provider is
registered and analytics that depend on that source degrade cleanly.

The provider ``source_type`` matches the analytics engine's
``analytic_config.type`` string (e.g. ``"PeatFileData"``,
``"ElasticsearchIndex"``), so a provider can be looked up for a given analytic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

__all__ = [
    "DataSourceProvider",
    "register_data_source_provider",
    "get_data_source_providers",
    "get_data_source_provider",
    "clear_data_source_providers",
]


@dataclass(frozen=True)
class DataSourceProvider:
    """Describes a webapp data-source an analytic can run against.

    ``key``          -- stable identifier for the provider (e.g. ``"peat_file"``).
    ``source_type``  -- matches the engine ``analytic_config.type`` this provider
                        serves (e.g. ``"PeatFileData"``).
    ``label``        -- human-readable label for UI.
    ``list_datasets``-- optional callable returning a list of selectable datasets
                        as ``{"id": ..., "label": ...}`` dicts (used to populate a
                        UI dropdown). Sources with no enumerable datasets (e.g. a
                        free-form Elasticsearch index name) may omit this.
    ``resolve_index``-- optional callable mapping a chosen dataset id to the
                        concrete index name / filesystem path the engine consumes.
                        If omitted, the dataset id is used verbatim.
    """

    key: str
    source_type: str
    label: str
    list_datasets: Callable[[], list[dict]] | None = None
    resolve_index: Callable[[str], str] | None = None

    @property
    def enumerable(self) -> bool:
        """Return ``True`` when this provider can list selectable datasets."""
        return self.list_datasets is not None

    def get_datasets(self) -> list[dict]:
        """Return selectable datasets, or an empty list when not enumerable."""
        if self.list_datasets is None:
            return []
        return list(self.list_datasets())

    def resolve(self, dataset_id: str) -> str:
        """Resolve a dataset id to the concrete index/path for the engine."""
        if self.resolve_index is None:
            return dataset_id
        return self.resolve_index(dataset_id)


# Providers keyed by their ``source_type``. Registration is idempotent per key:
# re-registering the same source_type replaces the prior provider.
_PROVIDERS: dict[str, DataSourceProvider] = {}


def register_data_source_provider(provider: DataSourceProvider) -> None:
    """Register (or replace) a data-source provider by its ``source_type``."""
    if not isinstance(provider, DataSourceProvider):
        raise TypeError("provider must be a DataSourceProvider")
    if not provider.source_type:
        raise ValueError("DataSourceProvider.source_type is required")
    _PROVIDERS[provider.source_type] = provider


def get_data_source_providers() -> tuple[DataSourceProvider, ...]:
    """Return all registered data-source providers."""
    return tuple(_PROVIDERS.values())


def get_data_source_provider(source_type: str) -> DataSourceProvider | None:
    """Return the provider serving ``source_type``, or ``None`` if unregistered."""
    return _PROVIDERS.get(source_type)


def clear_data_source_providers() -> None:
    """Remove all registered providers (primarily for tests)."""
    _PROVIDERS.clear()
