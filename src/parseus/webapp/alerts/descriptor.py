"""App descriptor for the alerts app.

Exposed via the ``parseus.apps`` entry point so Parseus can discover this app
when it is installed. See ``parseus.webapp.registry``.
"""

from __future__ import annotations

from parseus.webapp.registry import AppDescriptor


def get_app_descriptor() -> AppDescriptor:
    """Return the pluggable-app descriptor for the alerts app."""
    return AppDescriptor(
        key="alerts",
        app_config="parseus.webapp.alerts.apps.AlertsConfig",
        urlconf="parseus.webapp.alerts.urls",
        namespace="alerts",
        url_prefix="alerts/",
        nav_label="Alerts",
        nav_icon="bi bi-bell",
        nav_url_name="alerts:alerts_home",
        nav_order=40,
        nav_description=(
            "A centralized, real-time interface designed for operators to track, "
            "triage, and resolve system Sysmon and SCPI alerts and performance "
            "anomalies."
        )
    )
