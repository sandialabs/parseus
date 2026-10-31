"""Registry of per-app ASGI websocket routes.

Apps that provide Channels websocket consumers register their URL patterns
here (typically in ``AppConfig.ready``). The project ASGI entrypoint assembles
the websocket router from whatever is registered, so an app like ``pei`` can be
removed without breaking ASGI startup and without the project layer importing
that app's routing directly.
"""

from __future__ import annotations

__all__ = [
    "register_websocket_urlpatterns",
    "get_websocket_urlpatterns",
    "clear_websocket_urlpatterns",
]

# Registered patterns keyed by a source label (usually the app name) so
# re-registration by the same app is idempotent.
_PATTERNS: dict[str, list] = {}


def register_websocket_urlpatterns(source: str, patterns) -> None:
    """Register (or replace) an app's websocket URL patterns under ``source``."""
    _PATTERNS[source] = list(patterns)


def get_websocket_urlpatterns() -> list:
    """Return the flattened list of all registered websocket URL patterns."""
    flattened: list = []
    for patterns in _PATTERNS.values():
        flattened.extend(patterns)
    return flattened


def clear_websocket_urlpatterns() -> None:
    """Remove all registered websocket patterns (primarily for tests)."""
    _PATTERNS.clear()
