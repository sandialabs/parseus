"""Template context processor exposing the pluggable-app navigation.

Adds ``parseus_nav_items`` to every template context, built from the
installed-app registry. Templates loop over this instead of hard-coding
per-app ``{% url %}`` tags, so removing an app cleanly removes its navbar
entry and dashboard card without raising ``NoReverseMatch``.
"""

from __future__ import annotations

from .apps import iter_installed_app_descriptors


def navigation(request):
    """Return navigation items for installed apps, ordered by ``nav_order``."""
    items = [d for d in iter_installed_app_descriptors() if d.has_nav]
    items.sort(key=lambda d: (d.nav_order, d.nav_label or ""))
    nav_items = [
        {
            "key": d.key,
            "label": d.nav_label,
            "icon": d.nav_icon,
            "url_name": d.nav_url_name,
            "namespace": d.namespace,
            "description": d.nav_description,
        }
        for d in items
    ]
    return {"parseus_nav_items": nav_items}
