"""Parseus pluggable-app registry.

This package is the single source of truth for which Parseus feature apps are
available and how they wire into the project (installed-app config path, URL
namespace/prefix, and navigation metadata).

Apps are discovered from installed Python entry points (group
``parseus.apps``); each entry is a callable returning an :class:`AppDescriptor`.
A hard-coded built-in list is kept as a fallback for environments where that
entry-point metadata is unavailable or stale, so ``settings``, ``urls``, and
the navigation context processor always have a descriptor list to consume.
"""

from .apps import AppDescriptor, get_app_descriptors, iter_installed_app_descriptors
from .data_sources import (
    DataSourceProvider,
    clear_data_source_providers,
    get_data_source_provider,
    get_data_source_providers,
    register_data_source_provider,
)
from .periodic_tasks import (
    PeriodicTaskSpec,
    clear_periodic_task_specs,
    get_periodic_task_specs,
    register_periodic_tasks,
)
from .websockets import (
    clear_websocket_urlpatterns,
    get_websocket_urlpatterns,
    register_websocket_urlpatterns,
)

__all__ = [
    "AppDescriptor",
    "get_app_descriptors",
    "iter_installed_app_descriptors",
    "DataSourceProvider",
    "register_data_source_provider",
    "get_data_source_providers",
    "get_data_source_provider",
    "clear_data_source_providers",
    "PeriodicTaskSpec",
    "register_periodic_tasks",
    "get_periodic_task_specs",
    "clear_periodic_task_specs",
    "register_websocket_urlpatterns",
    "get_websocket_urlpatterns",
    "clear_websocket_urlpatterns",
]
