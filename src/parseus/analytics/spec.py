"""Analytic metadata objects used by the registry and runtime.

AnalyticSpec is the source of truth for built-in analytic metadata and default
deployment settings. Runtime/user input may layer environment-specific overrides
on top of these defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, Optional, Type

from parseus.analytics.base import Analytic
from parseus.analytics.docstring_metadata import (
    DocstringMetadata,
    parse_docstring_metadata,
)


class AnalyticSpecValidationError(ValueError):
    """Raised when analytic metadata or legacy config is invalid."""


def load_class(full_class_name: str) -> Type[Any]:
    """Load and return a class from a dotted import path."""
    module_name = full_class_name[: full_class_name.rfind(".")]
    base_class_name = full_class_name[full_class_name.rfind(".") + 1 :]
    module = __import__(module_name, fromlist=[base_class_name])
    return getattr(module, base_class_name)


def _family_from_class_path(class_path: str) -> str:
    """Best-effort family extraction for legacy analytics."""
    parts = class_path.split(".")
    try:
        analytics_index = parts.index("analytics")
    except ValueError:
        return "uncategorized"
    if len(parts) > analytics_index + 1:
        return parts[analytics_index + 1]
    return "uncategorized"


def _location_from_class_path(class_path: str) -> str:
    """Best-effort source module extraction for legacy analytics."""
    parts = class_path.split(".")
    try:
        analytics_index = parts.index("analytics")
    except ValueError:
        return ""
    return parts[analytics_index + 2] if len(parts) > analytics_index + 2 else ""


def _metadata_defaults(metadata: DocstringMetadata) -> Dict[str, Any]:
    """Map parsed docstring metadata onto AnalyticSpec field defaults."""
    return {
        "summary": metadata.summary,
        "detection_logic": metadata.detection_logic,
        "labels": list(metadata.labels),
        "mitre_techniques": list(metadata.mitre_techniques),
        "purdue_levels": list(metadata.purdue_levels),
    }


@dataclass(frozen=True)
class AnalyticSpec:
    """Declarative metadata for an analytic — the single source of truth.

    Fields are grouped by concern below. The grouping is currently flat (every
    field is a top-level attribute) for backwards-compatible access; a nested
    decomposition (e.g. ``spec.metadata.summary`` / ``spec.deployment.fit_idx`` /
    ``spec.capabilities.data_source``) is deferred to the front-end work, when
    the descriptor becomes a documented front-end API contract and its external
    shape is finalized once.

    The five concern-groups are:

    * **Identity** — how the analytic is named and located.
    * **Taxonomy** — how it is grouped/filtered in the UI.
    * **Runtime** — training requirement and description text.
    * **Deployment** — index/query/schedule config layered over by DB overrides.
    * **UI metadata** — structured fields the UI/API renders (promoted out of the
      docstring so nothing has to parse ``__doc__``).
    * **Capabilities** — the declared data-source / training / state / persistence
      intent, authoritative at runtime.
    """

    # --- Identity ---
    key: str
    class_path: str
    display_name: Optional[str] = None

    # --- Taxonomy ---
    family: str = "uncategorized"
    location: str = ""

    # --- Runtime ---
    requires_fit: bool = True
    train_desc: str = ""
    predict_desc: str = ""

    # --- Deployment (DB/user overrides layer on top of these defaults) ---
    fit_idx: Dict[str, Any] = field(default_factory=dict)
    run_idx: Dict[str, Any] = field(default_factory=dict)
    out_idx: Dict[str, Any] = field(default_factory=dict)
    init_args: Dict[str, Any] = field(default_factory=dict)
    schedule: int = 0
    pull_duration: int = 0
    suppression: str = "0s"
    tags: list[str] = field(default_factory=list)

    # --- UI metadata (structured fields the UI/API renders) ---
    summary: str = ""
    description: str = ""
    detection_logic: str = ""
    labels: list[str] = field(default_factory=list)
    mitre_techniques: list[str] = field(default_factory=list)
    purdue_levels: list[int] = field(default_factory=list)
    maturity: str = "experimental"
    owner: str = ""

    # --- Capabilities (declared data-source / training / persistence) ---
    data_source: Optional[Any] = None
    training: Optional[Any] = None
    persistence: Optional[Any] = None

    @property
    def name(self) -> str:
        """User-facing name, defaulting to the registry key."""
        return self.display_name or self.key

    @property
    def analytic_class(self) -> Type[Analytic]:
        """Load the analytic class represented by this spec."""
        return load_class(self.class_path)

    def instantiate(self, **kwargs) -> Analytic:
        """Instantiate the analytic class using spec defaults plus overrides."""
        init_args = {**self.init_args, **kwargs}
        return self.analytic_class(**init_args)

    def with_overrides(self, **overrides) -> "AnalyticSpec":
        """Return a copy of the spec with selected dataclass fields overridden."""
        return replace(self, **overrides)

    @classmethod
    def from_class(
        cls,
        analytic_class: Type[Analytic],
        *,
        key: str,
        **overrides: Any,
    ) -> "AnalyticSpec":
        """Build a spec directly from an analytic class.

        This is the entry point used by the ``@register_analytic`` decorator so
        a descriptor can be declared next to its analytic. The class path,
        ``requires_fit`` flag, and description default to values read from the
        class; anything explicitly passed in ``overrides`` wins.

        Unlike :meth:`from_config_entry`, this does not instantiate the analytic
        and does not require legacy ``*_idx`` config sections -- deployment
        details remain the job of the YAML/DB override layer.
        """
        if not isinstance(key, str) or not key:
            raise AnalyticSpecValidationError(
                "register_analytic requires a non-empty string key"
            )
        if not (isinstance(analytic_class, type) and issubclass(analytic_class, Analytic)):
            raise AnalyticSpecValidationError(
                f"register_analytic target for '{key}' must be an Analytic subclass"
            )

        class_path = f"{analytic_class.__module__}.{analytic_class.__qualname__}"
        docstring = analytic_class.__doc__ or ""
        metadata = parse_docstring_metadata(docstring)
        defaults: Dict[str, Any] = {
            "class_path": class_path,
            "requires_fit": bool(analytic_class.requires_fit()),
            "family": _family_from_class_path(class_path),
            "location": _location_from_class_path(class_path),
            **_metadata_defaults(metadata),
        }
        defaults.update(overrides)
        return cls(key=key, **defaults)

