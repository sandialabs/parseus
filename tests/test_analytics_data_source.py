"""Tests for analytics resolving PEAT data paths via the provider registry."""

import pytest

from parseus.webapp.analytics import views as analytics_views
from parseus.webapp.registry import (
    DataSourceProvider,
    clear_data_source_providers,
    register_data_source_provider,
)


def _restore_pei_provider():
    """Re-register the pei provider (cleared by some tests)."""
    from parseus.webapp.pei import data_source

    data_source.register()


def test_resolve_peat_index_uses_registered_provider():
    clear_data_source_providers()
    register_data_source_provider(
        DataSourceProvider(
            key="peat_file",
            source_type="PeatFileData",
            label="PEAT",
            resolve_index=lambda dataset_id: f"/runs/{dataset_id}",
        )
    )
    try:
        assert analytics_views._resolve_peat_index("run1") == "/runs/run1"
    finally:
        clear_data_source_providers()
        _restore_pei_provider()


def test_resolve_peat_index_raises_when_provider_missing():
    clear_data_source_providers()
    try:
        with pytest.raises(analytics_views.DataSourceUnavailableError):
            analytics_views._resolve_peat_index("run1")
    finally:
        _restore_pei_provider()


def test_analytics_views_no_longer_import_pei_settings():
    """analytics.views must not reference PEAT_PULL_DIR directly anymore."""
    import inspect

    source = inspect.getsource(analytics_views)
    assert "PEAT_PULL_DIR" not in source


def test_peat_datasets_endpoint_lists_via_provider():
    """The analytics datasets endpoint returns ids from the registered provider."""
    from django.test import RequestFactory

    clear_data_source_providers()
    register_data_source_provider(
        DataSourceProvider(
            key="peat_file",
            source_type="PeatFileData",
            label="PEAT",
            list_datasets=lambda: [
                {"id": "run_a", "label": "run_a"},
                {"id": "run_b", "label": "run_b"},
            ],
        )
    )
    try:
        request = RequestFactory().get("/analytics/peat_datasets/")
        response = analytics_views.peat_datasets(request)
        import json

        assert json.loads(response.content) == ["run_a", "run_b"]
    finally:
        clear_data_source_providers()
        _restore_pei_provider()


def test_peat_datasets_endpoint_empty_when_no_provider():
    """The datasets endpoint returns an empty list when no provider is installed."""
    from django.test import RequestFactory

    clear_data_source_providers()
    try:
        request = RequestFactory().get("/analytics/peat_datasets/")
        response = analytics_views.peat_datasets(request)
        import json

        assert json.loads(response.content) == []
    finally:
        _restore_pei_provider()


def test_analytics_js_does_not_call_pei_url():
    """The analytics peat JS must call its own endpoint, not the pei URL."""
    from pathlib import Path

    js_path = (
        Path(analytics_views.__file__).parent
        / "static"
        / "js"
        / "peat_analytics.js"
    )
    source = js_path.read_text(encoding="utf-8")
    assert "/peat/results/" not in source
    assert "/analytics/peat_datasets/" in source

