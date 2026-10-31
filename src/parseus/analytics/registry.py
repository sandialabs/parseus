"""Registry for analytics metadata.

This is intentionally lightweight.  It gives Parseus a single place to collect
analytic metadata today, while leaving room for package entry points or pluggy
hooks later.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any, Callable, Iterable, Optional, TypeVar

from parseus.analytics.spec import AnalyticSpec

logger = logging.getLogger("parseus.analytics")

#: Entry-point group used to auto-discover analytics shipped by installed
#: packages.  Mirrors the ``parseus.apps`` group used for Django feature apps
#: (see ``parseus.webapp.registry``).  Each entry point loads a module so its
#: ``@register_analytic`` decorators execute and populate the registry.
ENTRY_POINT_GROUP = "parseus.analytics"

_ANALYTIC_SPECS: "OrderedDict[str, AnalyticSpec]" = OrderedDict()

_AnalyticT = TypeVar("_AnalyticT", bound=type)


class AnalyticRegistryError(ValueError):
    """Raised when analytic registry operations are invalid."""


def register_spec(spec: AnalyticSpec, *, replace: bool = False) -> AnalyticSpec:
    """Register an already-built analytic spec and return it.

    This is the low-level registration primitive. To declare and register an
    analytic next to its class, use the :func:`register_analytic` decorator,
    which builds the spec for you and calls this.

    Parameters
    ----------
    spec:
        The analytic metadata to register.
    replace:
        If false, registering the same key twice raises an error. If true, the
        existing entry is replaced.
    """
    if spec.key in _ANALYTIC_SPECS and not replace:
        raise AnalyticRegistryError(f"Analytic '{spec.key}' is already registered")
    _ANALYTIC_SPECS[spec.key] = spec
    return spec


def unregister_analytic(key: str) -> None:
    """Remove an analytic spec from the registry if present."""
    _ANALYTIC_SPECS.pop(key, None)


def get_analytic_spec(key: str) -> AnalyticSpec:
    """Return a registered analytic spec by key."""
    try:
        return _ANALYTIC_SPECS[key]
    except KeyError as exc:
        raise AnalyticRegistryError(f"Analytic '{key}' is not registered") from exc


def find_spec_for_class(analytic_class: type) -> Optional[AnalyticSpec]:
    """Return the registered spec for an analytic class, or ``None``.

    Matches on the fully-qualified class path so callers holding an analytic
    instance can recover its declared capabilities. Returns ``None`` when the
    class is not registered (e.g. ad-hoc test analytics), letting callers fall
    back to legacy config.
    """
    class_path = f"{analytic_class.__module__}.{analytic_class.__qualname__}"
    return find_spec_for_class_path(class_path)


def find_spec_for_class_path(class_path: str) -> Optional[AnalyticSpec]:
    """Return the registered spec whose ``class_path`` matches, or ``None``.

    The string-keyed counterpart to :func:`find_spec_for_class`: usable
    wherever only the dotted class path is on hand (e.g. ``Analytic.analytic_class``
    in the DB) without needing to import/load the class first.
    """
    for spec in _ANALYTIC_SPECS.values():
        if spec.class_path == class_path:
            return spec
    return None


def list_analytic_specs(family: Optional[str] = None) -> list[AnalyticSpec]:
    """List registered analytic specs, optionally filtered by family."""
    specs = list(_ANALYTIC_SPECS.values())
    if family is not None:
        specs = [spec for spec in specs if spec.family == family]
    return specs


def clear_registry() -> None:
    """Clear all registered analytic specs.

    Intended mainly for tests and management commands that intentionally rebuild
    the registry from a config file.
    """
    _ANALYTIC_SPECS.clear()


def register_specs(
    specs: Iterable[AnalyticSpec],
    *,
    replace: bool = False,
) -> list[AnalyticSpec]:
    """Register a sequence of analytic specs."""
    return [register_spec(spec, replace=replace) for spec in specs]


def register_analytic(
    *,
    key: str,
    replace: bool = False,
    **spec_overrides: Any,
) -> Callable[[_AnalyticT], _AnalyticT]:
    """Decorator that declares and registers an analytic next to its class.

    Usage::

        @register_analytic(key="excess_conversations", family="network_anomalies")
        class ExcessiveConversationAnalytic(Analytic):
            ...

    The decorated class is returned unchanged; a matching :class:`AnalyticSpec`
    is built via :meth:`AnalyticSpec.from_class` and added to the registry as a
    side effect. It makes the analytic discoverable without editing any central
    list.

    :param key: Stable registry key for the analytic.
    :param replace: If false (default), re-registering the same key raises.
    :param spec_overrides: Any :class:`AnalyticSpec` field to set explicitly
        (e.g. ``family``, ``display_name``, ``data_source``); values read from
        the class are used as defaults for anything omitted.
    """

    def decorator(analytic_class: _AnalyticT) -> _AnalyticT:
        spec = AnalyticSpec.from_class(analytic_class, key=key, **spec_overrides)
        register_spec(spec, replace=replace)
        return analytic_class

    return decorator


def discover_analytics() -> list[AnalyticSpec]:
    """Import analytics advertised via the ``parseus.analytics`` entry-point group.

    Each entry point is expected to load a module (or callable) whose import
    executes ``@register_analytic`` decorators, populating the registry as
    a side effect. Discovery is resilient: a failing entry point is logged and
    skipped rather than breaking the others.

    Returns the specs registered after discovery, in registration order.
    """
    try:
        from importlib.metadata import entry_points
    except Exception:  # pragma: no cover - importlib.metadata present on 3.11+
        return list_analytic_specs()

    try:
        eps = entry_points(group=ENTRY_POINT_GROUP)
    except Exception:
        logger.exception("Failed to enumerate '%s' entry points", ENTRY_POINT_GROUP)
        return list_analytic_specs()

    for entry_point in eps:
        try:
            loaded = entry_point.load()
            # Support both a bare module (import side effects register the
            # analytics) and a callable that performs registration.
            if callable(loaded):
                loaded()
        except Exception:
            logger.exception(
                "Failed to load analytics entry point '%s'", entry_point.name
            )
            continue

    return list_analytic_specs()

