"""Declarative capability types for analytics.

Each analytic declares three orthogonal capabilities on its
``@register_analytic`` descriptor:

- **data source**: an :class:`ElasticsearchSource` / :class:`PeatFileSource`
  (Elasticsearch sources carry per-phase :class:`IndexQuery` intent);
- **training**: :class:`Supervised` or :class:`Unsupervised`;
- **persistence**: :class:`JoblibArtifact` (a versioned joblib artifact — see
  :mod:`parseus.analytics.persistence`).

Run-to-run state is *not* a declared capability type: whether an analytic
re-alerts a standing finding is controlled at runtime by a configurable
alert-suppression window (see :mod:`parseus.analytics.core.suppression`), not by
a static stateful/stateless class.

These are small, explicit, immutable objects. Each analytic declares its
capabilities directly on the descriptor; the descriptor is the sole source of
truth (there is no runtime inference from analytic attributes).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Data source
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IndexQuery:
    """Query intent for one phase (fit or run) against a datastore index.

    Mirrors the per-phase attributes an analytic exposes today so the factory
    can later build the runtime data source from this instead of reading loose
    attributes off the analytic.
    """

    query: Optional[Dict[str, Any]] = None
    aggs: Optional[Dict[str, Any]] = None
    composite_agg: Optional[Dict[str, Any]] = None
    return_fields: Optional[List[str]] = None


@dataclass(frozen=True)
class SourceConfigField:
    """One deployment-config field a data source declares it accepts.

    Plain-Python (no Django): the webapp reads these to build and validate the
    per-analytic ``source_config`` JSON. ``name`` is the config key; ``type`` is
    the expected Python type for validation. ``default`` supplies the value when
    the key is absent — if it is callable (e.g. ``dict``) it is *called* to
    produce a fresh value, so mutable defaults are never shared.
    """

    name: str
    default: Any = None
    type: type = object

    def resolve_default(self) -> Any:
        """Return the default value, calling it when it is a factory (callable)."""
        return self.default() if callable(self.default) else self.default


@dataclass(frozen=True)
class DataSource:
    """Base class for a declared analytic data source.

    Data source subclasses declare the source-specific query/configuration shape
    for an analytic. Runtime data-source construction is handled by the
    datastore source factory.
    """

    def config_schema(self) -> List[SourceConfigField]:
        """Return the deployment-config fields this source type accepts.

        The per-analytic ``source_config`` (stored by the webapp) is keyed by
        these field names; a source with no extra config returns an empty list.
        Declaring config here keeps a source's config shape cohesive with the
        source itself, so adding a new source type needs no model/schema change.
        """
        return []

    def apply_config(
        self, cfg: Dict[str, Any], source_config: Dict[str, Any]
    ) -> None:
        """Write this source's ``source_config`` values into a runtime ``cfg``.

        The stored ``source_config`` is generic (keyed by :meth:`config_schema`
        field names); this maps those values into the source-specific *shape* the
        runtime consumes. The base source has no extra config and does nothing;
        each source that declares config overrides this. Called by
        ``AnalyticUserInput.get_analytic_cfg`` so that layer stays generic.
        """
        return None


@dataclass(frozen=True)
class ElasticsearchSource(DataSource):
    """Analytic backed by Elasticsearch/OpenSearch index data."""

    fit: Optional[IndexQuery] = None
    run: Optional[IndexQuery] = None

    def config_schema(self) -> List[SourceConfigField]:
        """ES deployment config: per-phase index filters, schedule, pull window."""
        return [
            SourceConfigField("fit_idx_filter", default=list, type=list),
            SourceConfigField("run_idx_filter", default=list, type=list),
            SourceConfigField("schedule", default=0, type=int),
            SourceConfigField("pull_duration", default=0, type=int),
        ]

    def apply_config(
        self, cfg: Dict[str, Any], source_config: Dict[str, Any]
    ) -> None:
        """Map ES config into the runtime cfg shape.

        Filters nest under the per-phase index dicts (``fit_idx``/``run_idx``);
        the fit filter is only applied when ``cfg`` has a ``fit_idx`` (i.e. the
        analytic requires fitting). ``schedule`` and ``pull_duration`` are
        top-level cfg keys.
        """
        if "fit_idx" in cfg:
            cfg["fit_idx"]["filter"] = source_config.get("fit_idx_filter", [])
        if "run_idx" in cfg:
            cfg["run_idx"]["filter"] = source_config.get("run_idx_filter", [])
        cfg["schedule"] = source_config.get("schedule", 0)
        cfg["pull_duration"] = source_config.get("pull_duration", 0)


@dataclass(frozen=True)
class PeatFileSource(DataSource):
    """Analytic backed by PEAT result-directory data."""


class SourceConfigError(ValueError):
    """Raised when a ``source_config`` does not match its source's schema."""


def validate_source_config(
    data_source: Optional[DataSource], source_config: Dict[str, Any]
) -> Dict[str, Any]:
    """Validate ``source_config`` against a source's declared :meth:`config_schema`.

    Unknown keys and wrong-typed values are rejected; missing declared fields are
    filled with their (factory-resolved) defaults. Returns the validated mapping.
    This keeps ``source_config`` structured, validated data rather than a
    free-form dict — the schema the source declares is authoritative.

    :raises SourceConfigError: on an unknown key or a value of the wrong type.
    """
    source_config = dict(source_config or {})
    if data_source is None:
        if source_config:
            raise SourceConfigError(
                "source_config supplied for an analytic with no declared data source"
            )
        return {}

    schema = {field.name: field for field in data_source.config_schema()}
    unknown = set(source_config) - set(schema)
    if unknown:
        raise SourceConfigError(
            f"Unknown source_config keys for {type(data_source).__name__}: "
            f"{sorted(unknown)}"
        )

    validated: Dict[str, Any] = {}
    for name, field in schema.items():
        if name in source_config:
            value = source_config[name]
            if field.type is not object and not isinstance(value, field.type):
                raise SourceConfigError(
                    f"source_config[{name!r}] must be {field.type.__name__}, "
                    f"got {type(value).__name__}"
                )
            validated[name] = value
        else:
            validated[name] = field.resolve_default()
    return validated


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Training:
    """Base class for an analytic's training requirement."""

    @property
    def requires_fit(self) -> bool:
        raise NotImplementedError


@dataclass(frozen=True)
class Supervised(Training):
    """Analytic that must be fit on training data before it can run."""

    @property
    def requires_fit(self) -> bool:
        return True


@dataclass(frozen=True)
class Unsupervised(Training):
    """Analytic that can run without any prior training."""

    @property
    def requires_fit(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Persistence:
    """Base class for how a trained analytic is saved/loaded."""


@dataclass(frozen=True)
class JoblibArtifact(Persistence):
    """Versioned joblib artifact with a schema-versioned manifest.

    See :mod:`parseus.analytics.persistence` for the on-disk format.
    """

    schema_version: int = 1


@dataclass(frozen=True)
class Capabilities:
    """The declared capabilities of an analytic."""

    data_source: Optional[DataSource] = None
    training: Optional[Training] = None
    persistence: Optional[Persistence] = None
