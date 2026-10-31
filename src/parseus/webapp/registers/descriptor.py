"""App descriptor for the registers app.

Exposed via the ``parseus.apps`` entry point so Parseus can discover this app
when it is installed. See ``parseus.webapp.registry``.
"""

from __future__ import annotations

from parseus.webapp.registry import AppDescriptor


def get_app_descriptor() -> AppDescriptor:
    """Return the pluggable-app descriptor for the registers app."""
    return AppDescriptor(
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
    )
