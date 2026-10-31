"""Tests for data-source-declared deployment config schemas.

Each :class:`DataSource` capability declares the deployment-config fields it
accepts (:meth:`config_schema`). The webapp uses these to build/validate a
per-analytic ``source_config``; declaring them on the capability keeps a
source's config shape cohesive with the source and lets a new source type be
added without a model/schema change.
"""

from __future__ import annotations

import pytest

from parseus.analytics.capabilities import (
    DataSource,
    ElasticsearchSource,
    PeatFileSource,
    SourceConfigField,
)


def test_base_source_declares_no_config():
    assert DataSource().config_schema() == []


def test_peat_source_declares_no_extra_config():
    # PEAT needs only the universal index fields; no source-specific config.
    assert PeatFileSource().config_schema() == []


def test_elasticsearch_source_declares_its_config_fields():
    fields = {f.name: f for f in ElasticsearchSource().config_schema()}
    assert set(fields) == {
        "fit_idx_filter",
        "run_idx_filter",
        "schedule",
        "pull_duration",
    }
    assert fields["schedule"].type is int
    assert fields["schedule"].default == 0
    # dict fields use a factory default so no mutable default is shared.
    assert fields["fit_idx_filter"].type is list
    assert fields["fit_idx_filter"].resolve_default() == []


def test_resolve_default_calls_factories_but_returns_scalars_as_is():
    assert SourceConfigField("x", default=dict, type=dict).resolve_default() == {}
    assert SourceConfigField("n", default=5, type=int).resolve_default() == 5

    # A factory returns a *fresh* object each call (not a shared instance).
    field = SourceConfigField("d", default=dict, type=dict)
    first = field.resolve_default()
    first["mutated"] = True
    assert field.resolve_default() == {}


# --- validation --------------------------------------------------------------


def test_validate_fills_defaults_for_missing_fields():
    from parseus.analytics.capabilities import validate_source_config

    validated = validate_source_config(ElasticsearchSource(), {"schedule": 60})
    assert validated["schedule"] == 60
    assert validated["pull_duration"] == 0
    assert validated["fit_idx_filter"] == []


def test_validate_rejects_unknown_keys():
    from parseus.analytics.capabilities import (
        SourceConfigError,
        validate_source_config,
    )

    with pytest.raises(SourceConfigError, match="Unknown source_config"):
        validate_source_config(ElasticsearchSource(), {"nope": 1})


def test_validate_rejects_wrong_type():
    from parseus.analytics.capabilities import (
        SourceConfigError,
        validate_source_config,
    )

    with pytest.raises(SourceConfigError, match="must be int"):
        validate_source_config(ElasticsearchSource(), {"schedule": "soon"})


def test_validate_no_source_rejects_nonempty_config():
    from parseus.analytics.capabilities import (
        DataSource,
        SourceConfigError,
        validate_source_config,
    )

    assert validate_source_config(None, {}) == {}
    with pytest.raises(SourceConfigError):
        validate_source_config(None, {"x": 1})
    # A source with no declared config also rejects extra keys.
    with pytest.raises(SourceConfigError):
        validate_source_config(DataSource(), {"x": 1})
