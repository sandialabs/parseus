"""Logging configuration owned by the analytics app.

Previously the ``analytics`` logger, its stream handler, and the
``analytic_format`` formatter lived in the project's ``LOGGING`` dict. Because
Django applies ``LOGGING`` once at startup via ``dictConfig``, an installable
app configures its own logger programmatically in ``AppConfig.ready`` instead.

``configure_logging`` is idempotent: it only attaches the handler when the
logger has none of its own, so re-running it (or a project that already
configures the logger) is safe.
"""

from __future__ import annotations

import logging

ANALYTICS_LOGGER_NAME = "analytics"
_ANALYTIC_FORMAT = "%(asctime)s %(name)-32s %(levelname)-8s %(message)s"
_ANALYTIC_DATEFMT = "%Y-%m-%d %H:%M:%S"


def configure_logging() -> None:
    """Configure the dedicated ``analytics`` logger if not already set up."""
    logger = logging.getLogger(ANALYTICS_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(_ANALYTIC_FORMAT, _ANALYTIC_DATEFMT))
        logger.addHandler(handler)
