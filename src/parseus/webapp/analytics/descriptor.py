"""App descriptor for the analytics app.

Exposed via the ``parseus.apps`` entry point so Parseus can discover this app
when it is installed. See ``parseus.webapp.registry``.
"""

from __future__ import annotations

from parseus.webapp.registry import AppDescriptor


def get_app_descriptor() -> AppDescriptor:
    """Return the pluggable-app descriptor for the analytics app."""
    return AppDescriptor(
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
    )
