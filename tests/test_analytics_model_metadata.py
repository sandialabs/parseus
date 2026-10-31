"""Tests for syncing the Django ``Analytic`` model from the descriptor registry.

These avoid a real test database (the suite has no pytest-django for this
file) by faking just enough of the Django ORM surface (`objects.filter(...)
.first()`, constructors, `save()`) that `save_analytic`/`upload_analytic_config`
exercise. Display-metadata resolution (``Analytic.spec``/``.name``/``.family``/
``.requires_fit``/``.summary``/etc.) is covered against the real model, below.
"""

from contextlib import nullcontext

import pytest

from parseus.analytics.registry import clear_registry, register_spec
from parseus.analytics.spec import AnalyticSpec
from parseus.webapp.analytics import utility_analytics
from parseus.webapp.analytics.models import Analytic, AnalyticUserInput


class _CapturingModel:
    """Fake Django model that records constructor kwargs and no-ops save()."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.id = 1
        self.__dict__.update(kwargs)

    def save(self, *args, **kwargs):
        return None


class _FakeQuerySet:
    """Minimal stand-in for a Django QuerySet supporting ``.first()``."""

    def __init__(self, obj=None):
        self._obj = obj

    def first(self):
        return self._obj


def _spec(**overrides):
    base = dict(
        key="documented",
        class_path="parseus.analytics.SysmonUnapprovedIpAnalytic",
        family="host_anomalies",
        requires_fit=True,
        summary="Detects a documented condition.",
        detection_logic="Uses a clear rule.",
        mitre_techniques=["T1040"],
        purdue_levels=[2],
        labels=["example", "documented"],
        maturity="stable",
    )
    base.update(overrides)
    return AnalyticSpec(**base)


def test_save_analytic_creates_new_row_with_only_identity_and_state(monkeypatch):
    """A new row only gets analytic_class/is_active/ui written to it: no
    display metadata, no family/requires_fit cache fields."""
    created = {}

    class _AnalyticManager:
        def filter(self, **kwargs):
            assert kwargs == {"analytic_class": _spec().class_path}
            return _FakeQuerySet(None)  # no existing row

    class _AnalyticModel(_CapturingModel):
        objects = _AnalyticManager()

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            created["analytic"] = self

    monkeypatch.setattr(utility_analytics, "Analytic", _AnalyticModel)
    monkeypatch.setattr(utility_analytics, "AnalyticUserInput", _CapturingModel)
    monkeypatch.setattr(
        utility_analytics.transaction, "atomic", lambda: nullcontext()
    )

    utility_analytics.save_analytic(_spec())

    analytic_obj = created["analytic"]
    assert analytic_obj.analytic_class == "parseus.analytics.SysmonUnapprovedIpAnalytic"
    assert analytic_obj.is_active is True
    # A fresh AnalyticUserInput was built from spec defaults and linked.
    assert analytic_obj.ui is not None
    # Nothing resolvable from the spec is a constructor kwarg: save_analytic
    # never passes family/requires_fit/display metadata onto the row.
    assert "family" not in analytic_obj.kwargs
    assert "requires_fit" not in analytic_obj.kwargs
    assert "summary" not in analytic_obj.kwargs
    assert "labels" not in analytic_obj.kwargs
    assert "name" not in analytic_obj.kwargs


def test_save_analytic_updates_existing_row_in_place(monkeypatch):
    """Re-syncing an already-known analytic_class reactivates the row without
    replacing it (preserving its PK and FK/UI links)."""

    class _ExistingAnalytic:
        def __init__(self):
            self.id = 42
            self.analytic_class = "parseus.analytics.SysmonUnapprovedIpAnalytic"
            self.is_active = True
            self.ui = "preexisting-ui-sentinel"
            self.saved = False

        def save(self, *args, **kwargs):
            self.saved = True

    existing = _ExistingAnalytic()

    class _AnalyticManager:
        def filter(self, **kwargs):
            return _FakeQuerySet(existing)

    class _AnalyticModel(_CapturingModel):
        objects = _AnalyticManager()

    new_ui_created = []

    class _AnalyticUserInputModel(_CapturingModel):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            new_ui_created.append(self)

    monkeypatch.setattr(utility_analytics, "Analytic", _AnalyticModel)
    monkeypatch.setattr(
        utility_analytics, "AnalyticUserInput", _AnalyticUserInputModel
    )
    monkeypatch.setattr(
        utility_analytics.transaction, "atomic", lambda: nullcontext()
    )

    utility_analytics.save_analytic(_spec())

    # The same row instance was updated and saved — never recreated.
    assert existing.saved is True
    assert existing.is_active is True
    # Its pre-existing AnalyticUserInput (operator overrides) was left alone.
    assert existing.ui == "preexisting-ui-sentinel"
    assert new_ui_created == []


def test_save_analytic_reactivates_a_previously_retired_row(monkeypatch):
    """An analytic that reappears in the registry has is_active flipped back
    to True (undoing a prior soft-delete)."""

    class _RetiredAnalytic:
        def __init__(self):
            self.analytic_class = "parseus.analytics.SysmonUnapprovedIpAnalytic"
            self.is_active = False
            self.ui = "preexisting-ui-sentinel"

        def save(self, *args, **kwargs):
            return None

    retired = _RetiredAnalytic()

    class _AnalyticManager:
        def filter(self, **kwargs):
            return _FakeQuerySet(retired)

    class _AnalyticModel(_CapturingModel):
        objects = _AnalyticManager()

    monkeypatch.setattr(utility_analytics, "Analytic", _AnalyticModel)
    monkeypatch.setattr(utility_analytics, "AnalyticUserInput", _CapturingModel)
    monkeypatch.setattr(
        utility_analytics.transaction, "atomic", lambda: nullcontext()
    )

    utility_analytics.save_analytic(_spec())

    assert retired.is_active is True


# --- upload_analytic_config syncs from the registry without wiping rows -----


class _FakeAnalyticManager:
    """Fake manager for the post-upsert retire-stale-rows query."""

    def __init__(self):
        self.exclude_kwargs = None
        self.filter_kwargs = None
        self.updated_with = None
        self.update_count = 1

    def exclude(self, **kwargs):
        self.exclude_kwargs = kwargs
        return self

    def filter(self, **kwargs):
        self.filter_kwargs = kwargs
        return self

    def update(self, **kwargs):
        self.updated_with = kwargs
        return self.update_count


def test_upload_analytic_config_sources_from_registry(monkeypatch):
    """The analytic set comes from the registry, upserted (not wiped)."""
    saved = []
    fake_manager = _FakeAnalyticManager()

    monkeypatch.setattr(
        utility_analytics.Analytic, "objects", fake_manager, raising=False
    )
    monkeypatch.setattr(
        utility_analytics.transaction, "atomic", lambda: nullcontext()
    )
    monkeypatch.setattr(utility_analytics, "save_analytic", saved.append)

    registry_spec = _spec()
    # upload_analytic_config imports discover_analytics from the registry module
    # at call time, so patch it there.
    import parseus.analytics.registry as registry_module

    monkeypatch.setattr(
        registry_module, "discover_analytics", lambda: [registry_spec]
    )

    utility_analytics.upload_analytic_config()

    assert len(saved) == 1
    assert saved[0].key == "documented"
    # No delete: rows no longer in the registry are soft-deleted (is_active
    # flipped False), scoped to currently-active rows excluding seen classes.
    assert fake_manager.exclude_kwargs == {
        "analytic_class__in": {registry_spec.class_path}
    }
    assert fake_manager.filter_kwargs == {"is_active": True}
    assert fake_manager.updated_with == {"is_active": False}


def test_upload_analytic_config_soft_deletes_rows_missing_from_registry(
    monkeypatch,
):
    """A row no longer provided by the registry is marked inactive, not
    deleted — its TrainedModel/AnalyticUserInput data is left untouched."""
    fake_manager = _FakeAnalyticManager()

    monkeypatch.setattr(
        utility_analytics.Analytic, "objects", fake_manager, raising=False
    )
    monkeypatch.setattr(
        utility_analytics.transaction, "atomic", lambda: nullcontext()
    )
    monkeypatch.setattr(utility_analytics, "save_analytic", lambda spec: None)

    import parseus.analytics.registry as registry_module

    monkeypatch.setattr(registry_module, "discover_analytics", lambda: [])

    utility_analytics.upload_analytic_config()

    # The only mutation on a stale row is the is_active flip; nothing is
    # ever deleted here.
    assert fake_manager.updated_with == {"is_active": False}


# --- Analytic display metadata resolves from the registry spec, live --------
#
# No DB round-trip needed: these properties are pure Python (registry lookup
# + string ops over an in-memory spec), so unsaved model instances exercise
# them identically to persisted ones.


@pytest.fixture
def registered_spec():
    """Register a spec for the duration of a test, restoring prior state."""
    snapshot = None

    def _register(**overrides):
        nonlocal snapshot
        import parseus.analytics.registry as registry_module

        snapshot = registry_module._ANALYTIC_SPECS.copy()
        clear_registry()
        spec = _spec(**overrides)
        register_spec(spec)
        return spec

    yield _register

    import parseus.analytics.registry as registry_module

    clear_registry()
    if snapshot is not None:
        registry_module._ANALYTIC_SPECS.update(snapshot)


def test_analytic_display_metadata_resolves_from_registered_spec(registered_spec):
    spec = registered_spec()
    ui = AnalyticUserInput()
    row = Analytic(analytic_class=spec.class_path, ui=ui)

    assert row.name == "documented"
    assert row.model == "SysmonUnapprovedIpAnalytic"
    assert row.family == "host_anomalies"
    assert row.requires_fit is True
    assert row.summary == "Detects a documented condition."
    assert row.detection_logic == "Uses a clear rule."
    assert row.mitre_techniques == ["T1040"]
    assert row.purdue_levels == [2]
    assert row.labels == ["example", "documented"]
    assert row.maturity == "stable"


def test_analytic_family_and_requires_fit_track_spec_changes_live(registered_spec):
    """family/requires_fit are not cached: changing the registered spec's
    values is reflected immediately, with no re-sync/save needed."""
    registered_spec(family="network_anomalies", requires_fit=False)
    row = Analytic(analytic_class="parseus.analytics.SysmonUnapprovedIpAnalytic")

    assert row.family == "network_anomalies"
    assert row.requires_fit is False


def test_analytic_display_metadata_degrades_safely_when_spec_is_gone(
    registered_spec,
):
    """A retired analytic (is_active=False, no matching spec left registered)
    must not raise when its display metadata is read."""
    spec = registered_spec()
    ui = AnalyticUserInput()
    row = Analytic(analytic_class=spec.class_path, is_active=False, ui=ui)

    clear_registry()  # simulate the plugin/class no longer being registered

    assert row.spec is None
    assert row.name == spec.class_path
    assert row.family == "uncategorized"
    assert row.requires_fit is True
    assert row.summary == ""
    assert row.detection_logic == ""
    assert row.mitre_techniques == []
    assert row.purdue_levels == []
    assert row.labels == []
    assert row.maturity == "experimental"


def test_analytic_ui_is_a_plain_one_to_one_relation():
    """Analytic.ui is a direct OneToOneField to AnalyticUserInput, not a
    GenericForeignKey — no content_type/object_id pair, no ContentType lookup
    needed to resolve either direction of the relation."""
    field = Analytic._meta.get_field("ui")

    assert field.one_to_one is True
    assert field.related_model is AnalyticUserInput
    assert not hasattr(Analytic, "content_type")
    assert not hasattr(Analytic, "object_id")
    # The reverse accessor Django generates from related_name="analytic" is
    # how AnalyticUserInput.analytic resolves back — no custom property/manual
    # ContentType query required (contrast the old GenericForeignKey version).
    assert "analytic" in [
        f.name
        for f in AnalyticUserInput._meta.get_fields()
        if f.is_relation
    ]
