"""Tests for the pluggable-app registry.

These tests also exercise that ``settings.INSTALLED_APPS`` is built from the
registry and that Django can set up with the resulting configuration.
"""

from parseus.webapp.registry import (
    AppDescriptor,
    get_app_descriptors,
    iter_installed_app_descriptors,
)


def test_builtin_apps_present():
    """All four built-in apps are registered with stable keys."""
    keys = {d.key for d in get_app_descriptors()}
    assert keys == {"pei", "registers", "analytics", "alerts"}


def test_descriptors_have_required_wiring_fields():
    """Every descriptor carries the fields the project layer relies on."""
    for descriptor in get_app_descriptors():
        assert isinstance(descriptor, AppDescriptor)
        assert descriptor.app_config
        assert descriptor.urlconf
        assert descriptor.namespace
        assert descriptor.url_prefix.endswith("/")


def test_nav_descriptors_are_complete():
    """Descriptors that opt into nav provide both a label and a url name."""
    for descriptor in get_app_descriptors():
        if descriptor.has_nav:
            assert descriptor.nav_label
            assert descriptor.nav_url_name
            assert ":" in descriptor.nav_url_name


def test_installed_apps_built_from_registry():
    """settings.INSTALLED_APPS contains each registered app's config path."""
    from django.conf import settings

    for descriptor in get_app_descriptors():
        assert descriptor.app_config in settings.INSTALLED_APPS


def test_iter_installed_matches_registry_when_all_installed():
    """With all built-in apps installed, iteration yields the full registry."""
    installed_keys = {d.key for d in iter_installed_app_descriptors()}
    assert installed_keys == {d.key for d in get_app_descriptors()}


def test_each_app_namespace_is_mounted_in_urlconf():
    """The root URLconf mounts every installed app under its namespace."""
    from django.urls import get_resolver

    resolver = get_resolver()
    for descriptor in iter_installed_app_descriptors():
        assert descriptor.namespace in resolver.namespace_dict


def test_nav_url_names_reverse():
    """Every nav url name reverses through the registry-built URLconf."""
    from django.urls import reverse

    for descriptor in iter_installed_app_descriptors():
        if descriptor.has_nav:
            # Raises NoReverseMatch if the app is not correctly mounted.
            assert reverse(descriptor.nav_url_name)


def test_navigation_context_processor_orders_by_nav_order():
    """The context processor emits nav items sorted by nav_order."""
    from parseus.webapp.registry.context_processors import navigation

    context = navigation(request=None)
    items = context["parseus_nav_items"]
    orders = [
        d.nav_order
        for key in [i["key"] for i in items]
        for d in get_app_descriptors()
        if d.key == key
    ]
    assert orders == sorted(orders)
    # Every emitted item has the fields the templates use.
    for item in items:
        assert item["label"] and item["url_name"] and item["namespace"]


def _request_with_session():
    """Build a GET request carrying an empty session for context processors."""
    from importlib import import_module

    from django.conf import settings as dj_settings
    from django.test import RequestFactory

    request = RequestFactory().get("/")
    engine = import_module(dj_settings.SESSION_ENGINE)
    request.session = engine.SessionStore()
    return request


def test_base_template_nav_renders_without_hardcoded_apps():
    """base.html renders nav items purely from the provided nav context."""
    from django.template.loader import render_to_string

    request = _request_with_session()
    # Provide a single synthetic nav item; template must render it and must
    # not depend on any specific app being installed.
    html = render_to_string(
        "base.html",
        {
            "parseus_nav_items": [
                {
                    "key": "demo",
                    "label": "Demo App",
                    "icon": "bi bi-star",
                    "url_name": "home",  # any resolvable name
                    "namespace": "demo",
                    "description": None,
                }
            ]
        },
        request=request,
    )
    assert "Demo App" in html
    assert "bi bi-star" in html


def test_home_template_renders_only_cards_with_descriptions():
    """home.html renders a dashboard card only for items with a description."""
    from django.template.loader import render_to_string

    request = _request_with_session()
    html = render_to_string(
        "home.html",
        {
            "parseus_nav_items": [
                {
                    "key": "with_desc",
                    "label": "Has Card",
                    "icon": "bi bi-star",
                    "url_name": "home",
                    "namespace": "with_desc",
                    "description": "A described card.",
                },
                {
                    "key": "no_desc",
                    "label": "No Card",
                    "icon": "bi bi-x",
                    "url_name": "home",
                    "namespace": "no_desc",
                    "description": None,
                },
            ]
        },
        request=request,
    )
    assert "Has Card" in html
    assert "A described card." in html
    # home.html extends base.html, so the navbar still lists every item; the
    # description-gating only controls dashboard *cards*. Exactly one card-link
    # should be rendered (the item that has a description).
    assert html.count('class="card-link"') == 1
