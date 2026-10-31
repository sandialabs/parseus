"""App descriptor for the pei (PEAT) app.

Exposed via the ``parseus.apps`` entry point so Parseus can discover this app
when it is installed. See ``parseus.webapp.registry``.
"""

from __future__ import annotations

from parseus.webapp.registry import AppDescriptor


def get_app_descriptor() -> AppDescriptor:
    """Return the pluggable-app descriptor for the pei app."""
    return AppDescriptor(
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
        nav_description=(
            'PEAT is a Operational Technology (OT) device interrogator, '
            'including pulling, parsing and uploading artifacts (configuration, '
            'firmware, process logic, etc.) and network discovery ("scanning").'
        ),
    )
