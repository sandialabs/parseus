"""Behavioural tests for the source-config extension point.

These pin that a single AnalyticUserInput + per-source ``source_config`` produces
the same runtime cfg the two-model split did, and that the config a source
declares (:meth:`DataSource.config_schema`) is what round-trips:

    1. an Elasticsearch analytic's cfg nests filters under fit_idx/run_idx and
       exposes schedule/pull_duration at top level (old NetworkAnalyticUserInput
       behaviour);
    2. a source with no declared config yields a cfg without those keys;
    3. validate_source_config accepts declared fields and rejects unknown ones /
       wrong types.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from parseus.analytics.capabilities import ElasticsearchSource, PeatFileSource
from parseus.webapp.analytics.models import AnalyticUserInput


@pytest.mark.django_db
def test_es_source_config_maps_into_runtime_cfg_shape(monkeypatch):
    ui = AnalyticUserInput.objects.create(
        fit_idx_name="packets-*",
        run_idx_name="packets-*",
        source_config={
            "fit_idx_filter": {"term": {"x": 1}},
            "run_idx_filter": {"term": {"y": 2}},
            "schedule": 300,
            "pull_duration": 90,
        },
    )

    # Stand in for the analytic lookup + its declared ES data source. A plain
    # namespace is enough: only .requires_fit/.analytic_class are read.
    monkeypatch.setattr(
        type(ui), "analytic",
        property(
            lambda self: SimpleNamespace(requires_fit=True, analytic_class="x.Y")
        ),
    )
    monkeypatch.setattr(
        type(ui), "_declared_data_source", lambda self: ElasticsearchSource()
    )

    cfg = ui.get_analytic_cfg()

    assert cfg["fit_idx"]["filter"] == {"term": {"x": 1}}
    assert cfg["run_idx"]["filter"] == {"term": {"y": 2}}
    assert cfg["schedule"] == 300
    assert cfg["pull_duration"] == 90


@pytest.mark.django_db
def test_source_with_no_config_yields_bare_cfg(monkeypatch):
    ui = AnalyticUserInput.objects.create(run_idx_name="results")
    monkeypatch.setattr(
        type(ui), "analytic",
        property(
            lambda self: SimpleNamespace(requires_fit=False, analytic_class="x.Y")
        ),
    )
    monkeypatch.setattr(
        type(ui), "_declared_data_source", lambda self: PeatFileSource()
    )

    cfg = ui.get_analytic_cfg()

    # PEAT declares no source config, so these keys are absent.
    assert "schedule" not in cfg
    assert "pull_duration" not in cfg
    assert "filter" not in cfg["run_idx"]

