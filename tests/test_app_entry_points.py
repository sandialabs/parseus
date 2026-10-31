"""Tests for the per-app descriptor entry-point contract (Phase 2, step 7).

Each app exposes a get_app_descriptor() callable (advertised via the
``parseus.apps`` entry-point group). These tests verify the callables exist and
agree with the current built-in registry, and -- when the package metadata has
been (re)installed with the entry points -- that they are discoverable.
"""

from parseus.webapp.registry import AppDescriptor, get_app_descriptors

_DESCRIPTOR_MODULES = {
    "pei": "parseus.webapp.pei.descriptor",
    "registers": "parseus.webapp.registers.descriptor",
    "analytics": "parseus.webapp.analytics.descriptor",
    "alerts": "parseus.webapp.alerts.descriptor",
}


def _load(module_path):
    from importlib import import_module

    return import_module(module_path).get_app_descriptor()


def test_each_app_exposes_descriptor_callable():
    for key, module_path in _DESCRIPTOR_MODULES.items():
        descriptor = _load(module_path)
        assert isinstance(descriptor, AppDescriptor)
        assert descriptor.key == key


def test_app_descriptors_match_builtin_registry():
    """Per-app descriptors equal the current built-in registry entries."""
    builtin = {d.key: d for d in get_app_descriptors()}
    for key, module_path in _DESCRIPTOR_MODULES.items():
        assert _load(module_path) == builtin[key]


def test_entry_points_resolve_when_registered():
    """If the parseus.apps entry points are installed, they load descriptors.

    Skips cleanly when the editable install predates the entry points (they are
    picked up after a reinstall); this keeps the test green in either state.
    """
    from importlib.metadata import entry_points

    eps = entry_points(group="parseus.apps")
    if not eps:
        import pytest

        pytest.skip("parseus.apps entry points not registered in this install yet")

    keys = set()
    for ep in eps:
        descriptor = ep.load()()
        assert isinstance(descriptor, AppDescriptor)
        keys.add(descriptor.key)
    assert keys == set(_DESCRIPTOR_MODULES)
