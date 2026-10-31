"""App descriptors and the built-in Parseus app registry.

An :class:`AppDescriptor` captures everything the project layer needs to know
about a pluggable Parseus feature app:

* ``app_config`` -- dotted path to the Django ``AppConfig`` (for
  ``INSTALLED_APPS``).
* ``urlconf`` / ``namespace`` / ``url_prefix`` -- how the app's URLs are
  mounted by the root URLconf.
* ``nav_*`` -- optional navigation metadata rendered in the shared navbar.

The registry discovers apps at runtime from the ``parseus.apps`` entry-point
group (each entry is a callable returning an :class:`AppDescriptor`). The
hard-coded :data:`_BUILTIN_APPS` tuple is retained as a resilient fallback for
environments where installed-package metadata is unavailable or stale (e.g. an
editable checkout that has not been reinstalled), and as a well-known default.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("parseus")

#: Entry-point group apps advertise their descriptor callables under.
ENTRY_POINT_GROUP = "parseus.apps"


@dataclass(frozen=True)
class AppDescriptor:
    """Describes one pluggable Parseus feature app."""

    #: Short, stable identifier for the app (used as a dict key / log label).
    key: str
    #: Dotted path to the Django ``AppConfig`` subclass.
    app_config: str
    #: Dotted path to the app's URLconf module.
    urlconf: str
    #: URL namespace the app is mounted under (e.g. ``"analytics"``).
    namespace: str
    #: URL path prefix the app is mounted at (e.g. ``"analytics/"``).
    url_prefix: str
    #: Human-readable label for the navigation entry (``None`` = no nav item).
    nav_label: str | None = None
    #: Bootstrap icon class for the navigation entry.
    nav_icon: str | None = None
    #: ``namespace:name`` URL used by the navigation entry.
    nav_url_name: str | None = None
    #: Sort order for navigation entries (lower shows first).
    nav_order: int = 100
    #: Optional longer description rendered on the home dashboard card.
    nav_description: str | None = None
    #: Whether this app provides Channels websocket consumers (requires the
    #: ``channels``/``daphne`` stack to be installed and enabled).
    provides_websockets: bool = False
    #: Importable module names this app's UI requires (its optional extra). If
    #: any are not importable, the app is skipped during discovery so a base
    #: install without the app's extra boots cleanly. Example: ``("peat",)``.
    requires: tuple[str, ...] = ()

    @property
    def has_nav(self) -> bool:
        """Return ``True`` when this app contributes a navbar entry."""
        return bool(self.nav_label and self.nav_url_name)

    def missing_requirements(self) -> tuple[str, ...]:
        """Return required modules that are not importable in this environment."""
        from importlib.util import find_spec

        missing = []
        for module_name in self.requires:
            try:
                found = find_spec(module_name) is not None
            except (ImportError, ValueError):
                found = False
            if not found:
                missing.append(module_name)
        return tuple(missing)


# Built-in Parseus feature apps. Order here is the canonical order used for
# INSTALLED_APPS and (via ``nav_order``) the navigation bar.
_BUILTIN_APPS: tuple[AppDescriptor, ...] = (
    AppDescriptor(
        key="pei",
        app_config="parseus.webapp.pei.apps.PeatConfig",
        urlconf="parseus.webapp.pei.urls",
        namespace="peat",
        url_prefix="peat/",
        nav_label="Peat",
        nav_icon="bi bi-router-fill",
        nav_url_name="peat:home",
        nav_order=10,
        provides_websockets=True,
        requires=("peat",),
    ),
    AppDescriptor(
        key="registers",
        app_config="parseus.webapp.registers.apps.RegistersConfig",
        urlconf="parseus.webapp.registers.urls",
        namespace="registers",
        url_prefix="registers/",
        nav_label="OT Registers",
        nav_icon="bi bi-graph-up",
        nav_url_name="registers:ot_network_analysis",
        nav_order=20,
        nav_description=(
            "Analysis of OT Protocol Modbus, includes visualization of register "
            "statistics and OT protocol function codes."
        ),
    ),
    AppDescriptor(
        key="analytics",
        app_config="parseus.webapp.analytics.apps.AnalyticsConfig",
        urlconf="parseus.webapp.analytics.urls",
        namespace="analytics",
        url_prefix="analytics/",
        nav_label="Analytics",
        nav_icon="bi bi-bar-chart-fill",
        nav_url_name="analytics:analytics",
        nav_order=30,
        nav_description=(
            "Run analytics on datasets to include network traffic located in "
            "elasticsearch or opensearch database. Analytics include supervised "
            "and unsupervised types."
        ),
    ),
    AppDescriptor(
        key="alerts",
        app_config="parseus.webapp.alerts.apps.AlertsConfig",
        urlconf="parseus.webapp.alerts.urls",
        namespace="alerts",
        url_prefix="alerts/",
        nav_label="Alerts",
        nav_icon="bi bi-bell",
        nav_url_name="alerts:alerts_home",
        nav_order=40,
    ),
)


def _discover_from_entry_points() -> tuple[AppDescriptor, ...]:
    """Return app descriptors discovered from the ``parseus.apps`` group.

    Resilient to individual bad entry points: a failing entry is logged and
    skipped rather than breaking discovery of the others. Returns an empty
    tuple when no valid descriptors are found.
    """
    try:
        from importlib.metadata import entry_points
    except Exception:  # pragma: no cover - importlib.metadata always present on 3.11+
        return ()

    try:
        eps = entry_points(group=ENTRY_POINT_GROUP)
    except Exception:
        logger.exception("Failed to enumerate '%s' entry points", ENTRY_POINT_GROUP)
        return ()

    discovered: list[AppDescriptor] = []
    seen_keys: set[str] = set()
    for entry_point in eps:
        try:
            factory = entry_point.load()
            descriptor = factory()
        except Exception:
            logger.exception(
                "Failed to load Parseus app entry point '%s'", entry_point.name
            )
            continue
        if not isinstance(descriptor, AppDescriptor):
            logger.error(
                "Parseus app entry point '%s' did not return an AppDescriptor",
                entry_point.name,
            )
            continue
        if descriptor.key in seen_keys:
            logger.warning(
                "Duplicate Parseus app key '%s' from entry point '%s'; ignoring",
                descriptor.key,
                entry_point.name,
            )
            continue
        missing = descriptor.missing_requirements()
        if missing:
            logger.warning(
                "Skipping Parseus app '%s': missing dependencies %s. "
                "Install the app's extra (e.g. parseus[%s]) to enable it.",
                descriptor.key,
                ", ".join(missing),
                descriptor.key,
            )
            continue
        seen_keys.add(descriptor.key)
        discovered.append(descriptor)

    discovered.sort(key=lambda d: (d.nav_order, d.key))
    return tuple(discovered)


def get_app_descriptors() -> tuple[AppDescriptor, ...]:
    """Return all known Parseus feature-app descriptors.

    Discovery order:

    1. Apps advertised via the ``parseus.apps`` entry-point group (the normal
       path once packages are installed).
    2. The built-in fallback list, used only when entry-point discovery yields
       nothing (e.g. metadata is missing or stale).

    This is the single source of truth consumed by ``settings`` (to build
    ``INSTALLED_APPS``), the root URLconf, and the navigation context
    processor.
    """
    discovered = _discover_from_entry_points()
    if discovered:
        return discovered
    logger.debug(
        "No '%s' entry points discovered; using built-in app fallback.",
        ENTRY_POINT_GROUP,
    )
    return _BUILTIN_APPS


def iter_installed_app_descriptors():
    """Yield descriptors for apps that are actually installed in Django.

    Safe to call at request time. During settings import (before the Django app
    registry is populated) this falls back to yielding all known descriptors so
    ``INSTALLED_APPS`` can be built from it.
    """
    try:
        from django.apps import apps as django_apps

        ready = django_apps.apps_ready
    except Exception:
        ready = False

    descriptors = get_app_descriptors()
    if not ready:
        yield from descriptors
        return

    for descriptor in descriptors:
        # AppConfig dotted path is "<module path>.<ClassName>"; the app's
        # importable name is the module-path portion.
        app_name = descriptor.app_config.rsplit(".apps.", 1)[0]
        if django_apps.is_installed(app_name):
            yield descriptor
