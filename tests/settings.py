"""Django settings for the test suite.

Lives outside ``src/`` so it is never packaged or shipped (the build only
includes ``src/``). It reuses the real project settings unchanged and overrides
only what tests need: test-only secrets (so importing settings does not fail
closed) and an in-memory SQLite database (fast, isolated, no on-disk file).

Point pytest at it via ``DJANGO_SETTINGS_MODULE = "tests.settings"`` (see
``[tool.pytest.ini_options]`` in ``pyproject.toml``). Production settings are
untouched and still refuse to boot without real secrets.
"""

from __future__ import annotations

import os

# Must be set before importing the base settings: it raises at import time when
# these are absent (production fails closed).
os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault(
    "DJANGO_ENCRYPTION_KEY",
    "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
)

from parseus.webapp.project.settings import *  # noqa: E402,F401,F403

# In-memory SQLite: fast, isolated per test run, and leaves no db file behind.
DATABASES = {  # noqa: F405
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
