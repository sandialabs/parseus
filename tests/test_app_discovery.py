"""Tests for entry-point-based app discovery (Phase 2, step 8)."""

from parseus.webapp.registry import apps as registry_apps
from parseus.webapp.registry import get_app_descriptors


def test_discovery_finds_all_four_apps():
    """Entry-point discovery returns the four built-in apps."""
    keys = {d.key for d in get_app_descriptors()}
    assert keys == {"pei", "registers", "analytics", "alerts"}


def test_discovery_sorted_by_nav_order():
    """Discovered descriptors are ordered by nav_order then key."""
    orders = [d.nav_order for d in get_app_descriptors()]
    assert orders == sorted(orders)


def test_discovery_prefers_entry_points_over_builtin(monkeypatch):
    """When entry points resolve, discovery is used (not the builtin fallback)."""
    from parseus.webapp.registry.apps import AppDescriptor

    sentinel = AppDescriptor(
        key="only",
        app_config="x.apps.X",
        urlconf="x.urls",
        namespace="only",
        url_prefix="only/",
    )
    monkeypatch.setattr(
        registry_apps, "_discover_from_entry_points", lambda: (sentinel,)
    )
    assert get_app_descriptors() == (sentinel,)


def test_falls_back_to_builtin_when_no_entry_points(monkeypatch):
    """With no entry points, discovery falls back to the built-in list."""
    monkeypatch.setattr(registry_apps, "_discover_from_entry_points", lambda: ())
    result = get_app_descriptors()
    assert result is registry_apps._BUILTIN_APPS
    assert {d.key for d in result} == {"pei", "registers", "analytics", "alerts"}


def test_discovery_skips_bad_entry_point(monkeypatch):
    """A failing/invalid entry point is skipped without breaking discovery."""

    class _GoodEP:
        name = "good"

        @staticmethod
        def load():
            from parseus.webapp.registers.descriptor import get_app_descriptor

            return get_app_descriptor

    class _BoomEP:
        name = "boom"

        @staticmethod
        def load():
            raise RuntimeError("broken entry point")

    class _NotDescriptorEP:
        name = "bad_return"

        @staticmethod
        def load():
            return lambda: "not a descriptor"

    monkeypatch.setattr(
        registry_apps,
        "ENTRY_POINT_GROUP",
        registry_apps.ENTRY_POINT_GROUP,
        raising=False,
    )

    def fake_entry_points(group):
        assert group == registry_apps.ENTRY_POINT_GROUP
        return [_GoodEP(), _BoomEP(), _NotDescriptorEP()]

    # Patch importlib.metadata.entry_points used inside _discover_from_entry_points.
    import importlib.metadata as md

    monkeypatch.setattr(md, "entry_points", fake_entry_points)

    discovered = registry_apps._discover_from_entry_points()
    keys = {d.key for d in discovered}
    assert keys == {"registers"}  # only the good one survives


def test_missing_requirements_detects_absent_module():
    """missing_requirements reports modules that cannot be imported."""
    from parseus.webapp.registry.apps import AppDescriptor

    needs_missing = AppDescriptor(
        key="x",
        app_config="x.apps.X",
        urlconf="x.urls",
        namespace="x",
        url_prefix="x/",
        requires=("definitely_not_a_real_module_xyz",),
    )
    assert needs_missing.missing_requirements() == (
        "definitely_not_a_real_module_xyz",
    )

    needs_present = AppDescriptor(
        key="y",
        app_config="y.apps.Y",
        urlconf="y.urls",
        namespace="y",
        url_prefix="y/",
        requires=("os", "json"),
    )
    assert needs_present.missing_requirements() == ()


def test_discovery_skips_app_with_missing_requirements(monkeypatch):
    """An app whose required deps are absent is skipped during discovery."""
    from parseus.webapp.registry.apps import AppDescriptor

    class _PresentEP:
        name = "present"

        @staticmethod
        def load():
            return lambda: AppDescriptor(
                key="present",
                app_config="p.apps.P",
                urlconf="p.urls",
                namespace="present",
                url_prefix="present/",
                requires=("os",),
            )

    class _MissingDepEP:
        name = "missing"

        @staticmethod
        def load():
            return lambda: AppDescriptor(
                key="missing",
                app_config="m.apps.M",
                urlconf="m.urls",
                namespace="missing",
                url_prefix="missing/",
                requires=("definitely_not_a_real_module_xyz",),
            )

    import importlib.metadata as md

    monkeypatch.setattr(
        md, "entry_points", lambda group: [_PresentEP(), _MissingDepEP()]
    )

    keys = {d.key for d in registry_apps._discover_from_entry_points()}
    assert keys == {"present"}  # the app with the missing dep is dropped


def test_builtin_apps_declare_expected_requirements():
    """pei requires peat; other built-in apps declare no extra requirements."""
    builtin = {d.key: d for d in registry_apps._BUILTIN_APPS}
    assert builtin["pei"].requires == ("peat",)
    assert builtin["analytics"].requires == ()
    assert builtin["registers"].requires == ()
    assert builtin["alerts"].requires == ()
