"""Tests for common analytic interface helpers."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from parseus.analytics.capabilities import ElasticsearchSource, IndexQuery
from parseus.datastore.sources import factory as source_factory
from parseus.interfaces import common


class RecordingAnalytic:
    """Analytic test double that records run windows.

    ``fit_spec``/``run_spec`` are the per-phase :class:`IndexQuery` objects the
    runtime reads via :meth:`data_source`; tests set them to exercise query and
    return-field selection.
    """

    def __init__(self, fit_spec=None, run_spec=None):
        self.fit_documents = None
        self.run_windows = []
        self._fit_spec = fit_spec if fit_spec is not None else IndexQuery()
        self._run_spec = run_spec if run_spec is not None else IndexQuery()

    def data_source(self):
        return ElasticsearchSource(fit=self._fit_spec, run=self._run_spec)

    def fit(self, data):
        self.fit_documents = data

    def run_on_data(self, data, start, end):
        self.run_windows.append((start, end, data))
        return []


class AttributeErrorAnalytic(RecordingAnalytic):
    """Analytic test double that raises AttributeError while running."""

    def run_on_data(self, data, start, end):
        raise AttributeError("missing analytic attribute")


def test_scheduled_run_queries_each_schedule_window(monkeypatch):
    """Scheduled runs should fetch data only for the current pull window."""
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(seconds=25)
    calls = []

    def fake_get_timerange(ds_client, index_name, start=None, end=None):
        return start_time, end_time

    def fake_get_datastore_data(**kwargs):
        calls.append(kwargs)
        return [kwargs["start"], kwargs["end"]]

    start_time = start
    end_time = end
    monkeypatch.setattr(common, "get_timerange", fake_get_timerange)
    monkeypatch.setattr(source_factory, "get_datastore_data", fake_get_datastore_data)

    analytic = RecordingAnalytic()
    analytic_config = SimpleNamespace(
        type="ElasticsearchIndex",
        run_idx="packets-*",
        run_start=None,
        run_end=None,
        ip_filter="",
        schedule=10,
        tags=[],
    )

    alerts = common.run(
        ds_client=object(),
        analytic=analytic,
        analytic_config=analytic_config,
    )

    assert alerts == []
    assert [(call["start"], call["end"]) for call in calls] == [
        (start, start + timedelta(seconds=10)),
        (start + timedelta(seconds=10), start + timedelta(seconds=20)),
        (start + timedelta(seconds=20), end),
    ]
    assert [(window[0], window[1]) for window in analytic.run_windows] == [
        (start, start + timedelta(seconds=10)),
        (start + timedelta(seconds=10), start + timedelta(seconds=20)),
        (start + timedelta(seconds=20), end),
    ]


def test_fit_uses_declared_fit_return_fields(monkeypatch):
    calls = []

    def fake_get_datastore_data(*args, **kwargs):
        calls.append(kwargs)
        return ["fit-data"]

    monkeypatch.setattr(source_factory, "get_datastore_data", fake_get_datastore_data)
    monkeypatch.setattr(
        common,
        "get_timerange",
        lambda **kwargs: ("fit-start", "fit-end"),
    )

    analytic = RecordingAnalytic(fit_spec=IndexQuery(return_fields=["fit-only"]))
    analytic_config = SimpleNamespace(
        type="ElasticsearchIndex",
        fit_idx="fit-*",
        fit_start=None,
        fit_end=None,
        ip_filter="",
    )

    fitted = common.fit(
        ds_client=object(),
        analytic=analytic,
        analytic_config=analytic_config,
    )

    assert fitted is analytic
    assert analytic.fit_documents == ["fit-data"]
    assert calls[0]["return_fields"] == ["fit-only"]


def test_run_uses_declared_run_return_fields(monkeypatch):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(seconds=10)
    calls = []

    def fake_get_timerange(ds_client, index_name, start=None, end=None):
        return start_time, end_time

    def fake_get_datastore_data(**kwargs):
        calls.append(kwargs)
        return []

    start_time = start
    end_time = end
    monkeypatch.setattr(common, "get_timerange", fake_get_timerange)
    monkeypatch.setattr(source_factory, "get_datastore_data", fake_get_datastore_data)

    analytic = RecordingAnalytic(run_spec=IndexQuery(return_fields=["run-only"]))
    analytic_config = SimpleNamespace(
        type="ElasticsearchIndex",
        run_idx="packets-*",
        run_start=None,
        run_end=None,
        ip_filter="",
        schedule=0,
        tags=[],
    )

    common.run(
        ds_client=object(),
        analytic=analytic,
        analytic_config=analytic_config,
    )

    assert calls[0]["return_fields"] == ["run-only"]


def test_return_fields_default_to_none_when_undeclared(monkeypatch):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(seconds=10)
    calls = []

    def fake_get_timerange(ds_client, index_name, start=None, end=None):
        return start_time, end_time

    def fake_get_datastore_data(**kwargs):
        calls.append(kwargs)
        return []

    start_time = start
    end_time = end
    monkeypatch.setattr(common, "get_timerange", fake_get_timerange)
    monkeypatch.setattr(source_factory, "get_datastore_data", fake_get_datastore_data)

    analytic = RecordingAnalytic()
    analytic_config = SimpleNamespace(
        type="ElasticsearchIndex",
        run_idx="packets-*",
        run_start=None,
        run_end=None,
        ip_filter="",
        schedule=0,
        tags=[],
    )

    common.run(
        ds_client=object(),
        analytic=analytic,
        analytic_config=analytic_config,
    )

    assert calls[0]["return_fields"] is None


def test_run_does_not_suppress_analytic_attribute_errors(monkeypatch):
    """Analytic AttributeErrors should surface instead of returning no alerts."""
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(seconds=10)

    def fake_get_timerange(ds_client, index_name, start=None, end=None):
        return start_time, end_time

    def fake_get_datastore_data(**kwargs):
        return []

    start_time = start
    end_time = end
    monkeypatch.setattr(common, "get_timerange", fake_get_timerange)
    monkeypatch.setattr(source_factory, "get_datastore_data", fake_get_datastore_data)

    analytic_config = SimpleNamespace(
        type="ElasticsearchIndex",
        run_idx="packets-*",
        run_start=None,
        run_end=None,
        ip_filter="",
        schedule=0,
        tags=[],
    )

    with pytest.raises(AttributeError, match="missing analytic attribute"):
        common.run(
            ds_client=object(),
            analytic=AttributeErrorAnalytic(),
            analytic_config=analytic_config,
        )


# --- factory dispatch on declared DataSource capability (Phase 2c) ------------


def test_factory_dispatches_on_declared_capability_over_config_type():
    """A declared DataSource capability wins over the legacy config.type string."""
    from parseus.analytics.capabilities import ElasticsearchSource, PeatFileSource
    from parseus.datastore.sources.elasticsearch import ElasticsearchIndexDataSource
    from parseus.datastore.sources.peat_file import PeatFileDataSource

    # config says PEAT, capability says Elasticsearch -> capability wins.
    es_config = SimpleNamespace(type="PeatFileData")
    es_source = source_factory.build_data_source(
        object(),
        es_config,
        get_timerange=lambda **_: (None, None),
        data_source=ElasticsearchSource(),
    )
    assert isinstance(es_source, ElasticsearchIndexDataSource)

    # config says Elasticsearch, capability says PEAT -> capability wins.
    peat_config = SimpleNamespace(type="ElasticsearchIndex", fit_idx="/opt/data/")
    peat_source = source_factory.build_data_source(
        object(),
        peat_config,
        get_timerange=lambda **_: (None, None),
        data_source=PeatFileSource(),
    )
    assert isinstance(peat_source, PeatFileDataSource)


def test_factory_falls_back_to_config_type_without_capability():
    """Without a declared capability, the legacy config.type string is used."""
    from parseus.datastore.sources.base import DataSourceConfigurationError

    config = SimpleNamespace(type="PeatFileData")

    with pytest.raises(DataSourceConfigurationError, match="data source"):
        source_factory.build_data_source(
            object(),
            config,
            get_timerange=lambda **_: (None, None),
        )
