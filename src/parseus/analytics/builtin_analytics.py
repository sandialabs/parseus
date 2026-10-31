"""Built-in analytics registration hook.

Advertised via the ``parseus.analytics`` entry-point group (see ``pyproject.toml``
and ``parseus.analytics.registry.discover_analytics``). Importing this module
imports the built-in analytic modules, whose ``@register_analytic``
decorators populate the registry. The registry is the sole source of truth for
which analytics exist and their default deployment values; per-deployment
overrides come from the DB (set via the webapp) or an optional override file
passed to ``populate_analytics``.
"""

from __future__ import annotations

import importlib
import logging

logger = logging.getLogger("parseus.analytics")

# Modules whose import registers the built-in analytics via decorators.
_ANALYTIC_MODULES = (
    "parseus.analytics.host_anomalies.sysmon_unapproved_ip_analytic",
    "parseus.analytics.host_anomalies.sysmon_unapproved_user_analytic",
    "parseus.analytics.host_anomalies.sysmon_unapproved_device_analytic",
    "parseus.analytics.network_anomalies.excessive_conversation_analytic",
    "parseus.analytics.network_anomalies.port_scan_target_analytic",
    "parseus.analytics.network_anomalies.new_communications_analytic",
    "parseus.analytics.ot_network.ot_function_code_anomaly_analytic",
    "parseus.analytics.ot_internals.peat_device_change_analytic",
    "parseus.analytics.ot_internals.peat_file_change_analytic",
    "parseus.analytics.ot_internals.peat_service_change_analytic",
    "parseus.analytics.ot_internals.peat_process_change_analytic",
    "parseus.analytics.ot_internals.peat_io_change_analytic",
    "parseus.analytics.ot_internals.peat_auth_enumeration_analytic",
    "parseus.analytics.ot_internals.peat_firmware_change_analytic",
    "parseus.analytics.ot_internals.peat_logic_change_analytic",
    "parseus.analytics.scpi_analytics.scpi_compare_analytic",
    "parseus.analytics.scpi_analytics.scpi_value_ranges_analytic",
)


def register() -> None:
    """Import the built-in analytic modules so their decorators register them.

    Resilient: a module that fails to import is logged and skipped rather than
    breaking discovery of the others.
    """
    for module_name in _ANALYTIC_MODULES:
        try:
            importlib.import_module(module_name)
        except Exception:
            logger.exception("Failed to import built-in analytic module %s", module_name)


# Import side effect: loading this module via its entry point registers the
# built-in analytics.
register()
