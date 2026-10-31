"""Tests for the webapp data-source provider registry."""

import pytest

from parseus.webapp.registry import (
    DataSourceProvider,
    clear_data_source_providers,
    get_data_source_provider,
    get_data_source_providers,
    register_data_source_provider,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Ensure each test starts and ends with an empty provider registry."""
    clear_data_source_providers()
    yield
    clear_data_source_providers()


def test_register_and_lookup_by_source_type():
    provider = DataSourceProvider(
        key="peat_file",
        source_type="PeatFileData",
        label="PEAT files",
    )
    register_data_source_provider(provider)
    assert get_data_source_provider("PeatFileData") is provider
    assert get_data_source_providers() == (provider,)


def test_lookup_missing_returns_none():
    assert get_data_source_provider("PeatFileData") is None


def test_register_replaces_same_source_type():
    first = DataSourceProvider(key="a", source_type="X", label="A")
    second = DataSourceProvider(key="b", source_type="X", label="B")
    register_data_source_provider(first)
    register_data_source_provider(second)
    assert get_data_source_provider("X") is second
    assert len(get_data_source_providers()) == 1


def test_resolve_uses_callback_or_identity():
    with_resolver = DataSourceProvider(
        key="peat_file",
        source_type="PeatFileData",
        label="PEAT files",
        resolve_index=lambda dataset_id: f"/runs/{dataset_id}",
    )
    assert with_resolver.resolve("run1") == "/runs/run1"

    without_resolver = DataSourceProvider(
        key="es",
        source_type="ElasticsearchIndex",
        label="Elasticsearch",
    )
    assert without_resolver.resolve("packets*") == "packets*"


def test_datasets_enumerable_flag_and_listing():
    enumerable = DataSourceProvider(
        key="peat_file",
        source_type="PeatFileData",
        label="PEAT files",
        list_datasets=lambda: [{"id": "run1", "label": "run1"}],
    )
    assert enumerable.enumerable is True
    assert enumerable.get_datasets() == [{"id": "run1", "label": "run1"}]

    non_enumerable = DataSourceProvider(
        key="es",
        source_type="ElasticsearchIndex",
        label="Elasticsearch",
    )
    assert non_enumerable.enumerable is False
    assert non_enumerable.get_datasets() == []


def test_register_rejects_bad_input():
    with pytest.raises(TypeError):
        register_data_source_provider(object())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        register_data_source_provider(
            DataSourceProvider(key="x", source_type="", label="X")
        )
