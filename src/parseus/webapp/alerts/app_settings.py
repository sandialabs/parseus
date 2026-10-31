"""Default settings owned by the alerts app.

Previously defined in the project's ``settings.py``. These configure the
maintenance tasks (FTP cleanup / completed-file log) that ship with the alerts
app. ``apply_defaults`` only sets values that are not already provided, so
deployments can override them via project settings or environment variables.
"""

from __future__ import annotations

import os
from pathlib import Path


def _set_default(settings, name: str, value) -> None:
    """Set ``settings.<name> = value`` unless it is already defined."""
    if not hasattr(settings, name):
        setattr(settings, name, value)


def apply_defaults(settings) -> None:
    """Apply alerts default settings onto the Django ``settings`` object."""
    _set_default(
        settings,
        "FTP_CLEANUP_DIR",
        os.getenv("FTP_CLEANUP_DIR", str(Path.home() / "ftp")),
    )
    _set_default(
        settings,
        "FTP_COMPLETED_LOG_PATH",
        os.getenv(
            "FTP_COMPLETED_LOG_PATH",
            "/deploy/integrations/winlog/logstash/data/completed-files.log",
        ),
    )
