"""Tests that app-specific settings are owned by their apps.

After Step 4 of the modular-app work, PEAT_* settings are applied by the pei
app, FTP_* by the alerts app, and the ``analytics`` logger by the analytics
app -- rather than being defined in the project's ``settings.py``. These tests
confirm the values are present on the Django settings object once the apps are
ready, and that they are no longer hard-coded in the core settings module.
"""

import inspect
import logging


def test_pei_settings_applied():
    """pei applies its PEAT_* defaults onto the settings object."""
    from django.conf import settings

    assert settings.PEAT_ROOT
    assert settings.PEAT_RESULTS_DIR
    assert str(settings.PEAT_PULL_DIR).endswith("peat_pulls")
    assert str(settings.PEAT_SCAN_DIR).endswith("peat_scans")
    assert settings.PEAT_LOCK_TTL_SECONDS > 0
    assert settings.PEAT_LOCK_QUEUE_RETRY_SECONDS > 0
    assert settings.PEAT_LOCK_QUEUE_TIMEOUT_SECONDS > 0


def test_alerts_settings_applied():
    """alerts applies its FTP_* defaults onto the settings object."""
    from django.conf import settings

    assert settings.FTP_CLEANUP_DIR
    assert settings.FTP_COMPLETED_LOG_PATH


def test_analytics_logger_configured():
    """analytics configures its dedicated logger with a handler."""
    logger = logging.getLogger("analytics")
    assert logger.level == logging.DEBUG
    assert logger.propagate is False
    assert logger.handlers  # at least one handler attached


def test_core_settings_module_has_no_app_specific_config():
    """The project settings source no longer defines relocated app settings."""
    from parseus.webapp.project import settings as core_settings

    source = inspect.getsource(core_settings)
    # These identifiers should now live in their apps, not the core module.
    assert "PEAT_ROOT =" not in source
    assert "PEAT_LOCK_TTL_SECONDS =" not in source
    assert "FTP_CLEANUP_DIR =" not in source
    assert "analytic_handler" not in source
