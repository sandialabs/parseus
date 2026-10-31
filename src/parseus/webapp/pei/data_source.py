"""PEAT filesystem data-source provider for analytics.

Registers a :class:`~parseus.webapp.registry.DataSourceProvider` so the
analytics app can list PEAT pull runs and resolve a chosen run into the
filesystem path the analytics engine consumes -- without analytics importing
pei's settings or URLs.

The provider owns the knowledge of where PEAT pull output lives
(``settings.PEAT_PULL_DIR``); analytics only sees the generic provider.
"""

from __future__ import annotations

from pathlib import Path

from parseus.webapp.registry import (
    DataSourceProvider,
    register_data_source_provider,
)

#: Engine ``analytic_config.type`` this provider serves.
PEAT_SOURCE_TYPE = "PeatFileData"


def _pull_dir() -> Path:
    """Return the configured PEAT pull output directory."""
    from django.conf import settings

    return Path(settings.PEAT_PULL_DIR)


def list_pull_datasets() -> list[dict]:
    """Return selectable PEAT pull runs as ``{"id", "label"}`` dicts."""
    pull_dir = _pull_dir()
    if not pull_dir.is_dir():
        return []
    folders = sorted(item.name for item in pull_dir.iterdir() if item.is_dir())
    return [{"id": name, "label": name} for name in folders]


def resolve_pull_path(dataset_id: str) -> str:
    """Resolve a PEAT pull run name to its absolute filesystem path."""
    return str(_pull_dir() / dataset_id)


def build_provider() -> DataSourceProvider:
    """Build the PEAT filesystem data-source provider."""
    return DataSourceProvider(
        key="peat_file",
        source_type=PEAT_SOURCE_TYPE,
        label="PEAT run output",
        list_datasets=list_pull_datasets,
        resolve_index=resolve_pull_path,
    )


def register() -> None:
    """Register the PEAT filesystem data-source provider."""
    register_data_source_provider(build_provider())
