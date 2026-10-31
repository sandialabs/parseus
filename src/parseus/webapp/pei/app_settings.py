"""Default settings owned by the PEAT (pei) app.

These were previously defined in the project's ``settings.py``. Keeping them
with the app makes the app self-contained: when pei is installed its defaults
are applied on startup, and when it is removed the project's core settings no
longer carry PEAT-specific configuration.

``apply_defaults`` sets each value on the Django settings object only if it has
not already been provided, so a deployment can still override any of them in
the project settings or environment.
"""

from __future__ import annotations

import os


def _set_default(settings, name: str, value) -> None:
    """Set ``settings.<name> = value`` unless it is already defined."""
    if not hasattr(settings, name):
        setattr(settings, name, value)


def apply_defaults(settings) -> None:
    """Apply PEAT default settings onto the Django ``settings`` object."""
    peat_root = getattr(settings, "PEAT_ROOT", None) or (settings.MEDIA_ROOT / "peat")
    _set_default(settings, "PEAT_ROOT", peat_root)

    peat_results_dir = getattr(settings, "PEAT_RESULTS_DIR", None) or (
        peat_root / "peat_results"
    )
    _set_default(settings, "PEAT_RESULTS_DIR", peat_results_dir)

    _set_default(settings, "PEAT_PULL_DIR", peat_results_dir / "peat_pulls")
    _set_default(settings, "PEAT_SCAN_DIR", peat_results_dir / "peat_scans")

    _set_default(
        settings,
        "PEAT_LOCK_TTL_SECONDS",
        int(os.getenv("PEAT_LOCK_TTL_SECONDS", str(4 * 60 * 60))),
    )
    _set_default(
        settings,
        "PEAT_LOCK_HEARTBEAT_SECONDS",
        int(os.getenv("PEAT_LOCK_HEARTBEAT_SECONDS", "0")),
    )
    _set_default(
        settings,
        "PEAT_LOCK_QUEUE_RETRY_SECONDS",
        int(os.getenv("PEAT_LOCK_QUEUE_RETRY_SECONDS", "30")),
    )
    _set_default(
        settings,
        "PEAT_LOCK_QUEUE_RETRY_JITTER_SECONDS",
        int(os.getenv("PEAT_LOCK_QUEUE_RETRY_JITTER_SECONDS", "5")),
    )
    _set_default(
        settings,
        "PEAT_LOCK_QUEUE_TIMEOUT_SECONDS",
        int(os.getenv("PEAT_LOCK_QUEUE_TIMEOUT_SECONDS", "3600")),
    )
