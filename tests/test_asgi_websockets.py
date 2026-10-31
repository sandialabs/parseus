"""Tests for the optional websocket / ASGI wiring."""

from parseus.webapp.registry import (
    get_app_descriptors,
    get_websocket_urlpatterns,
)


def test_pei_registers_websocket_routes():
    """pei registers its websocket URL patterns with the registry."""
    patterns = get_websocket_urlpatterns()
    assert patterns, "expected at least one websocket route from pei"


def test_pei_descriptor_flags_websockets():
    """The pei descriptor advertises that it provides websockets."""
    pei = next(d for d in get_app_descriptors() if d.key == "pei")
    assert pei.provides_websockets is True


def test_channels_included_only_when_websocket_app_present():
    """settings includes channels because a websocket-providing app is installed."""
    from django.conf import settings

    provides = any(d.provides_websockets for d in get_app_descriptors())
    assert ("channels" in settings.INSTALLED_APPS) == provides


def test_asgi_does_not_hardcode_pei_routing():
    """asgi.py must not import pei routing directly anymore."""
    import inspect

    from parseus.webapp.project import asgi

    source = inspect.getsource(asgi)
    assert "parseus.webapp.pei" not in source
    assert "get_websocket_urlpatterns" in source


def test_asgi_application_builds():
    """The ASGI application object is constructed successfully."""
    from parseus.webapp.project import asgi

    assert asgi.application is not None
