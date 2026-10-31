"""Tests for the lightweight analytics metadata registry."""

import pytest

from parseus.analytics.base import Analytic
from parseus.analytics.registry import (
    AnalyticRegistryError,
    clear_registry,
    discover_analytics,
    get_analytic_spec,
    register_analytic,
)
from parseus.analytics.spec import (
    AnalyticSpec,
    AnalyticSpecValidationError,
)


class InitArgAnalytic(Analytic):
    """Analytic test double that requires constructor metadata input."""

    def __init__(self, display_suffix, **kwargs):
        super().__init__(pull_duration=1, **kwargs)
        self.predict_results_doc = f"Alerts for {display_suffix}"

    def _run(self, start, end, transformed_documents, state, **other_documents):
        return []

    @classmethod
    def requires_fit(cls) -> bool:
        return False


def minimal_config_entry(class_path="parseus.analytics.NewCommunicationsAnalytic"):
    return {
        "class": class_path,
        "fit_idx": {"index_name": "fit-*"},
        "run_idx": {"index_name": "run-*"},
        "out_idx": {"index_name": "alerts-example"},
        "schedule": 60,
    }


_REGISTRY_SNAPSHOT = None


def setup_function(_function=None):
    # Snapshot the ambient registry (populated by built-in decorators at import)
    # so these tests can work in a clean slate without destroying it for other
    # suites, then restore it in teardown.
    global _REGISTRY_SNAPSHOT
    import parseus.analytics.registry as registry_module

    _REGISTRY_SNAPSHOT = registry_module._ANALYTIC_SPECS.copy()
    clear_registry()


def teardown_function(_function=None):
    import parseus.analytics.registry as registry_module

    clear_registry()
    if _REGISTRY_SNAPSHOT is not None:
        registry_module._ANALYTIC_SPECS.update(_REGISTRY_SNAPSHOT)


# --- @register_analytic decorator + AnalyticSpec.from_class -------------


class DecoratedSupervisedAnalytic(Analytic):
    """A supervised analytic used to exercise the decorator."""

    def __init__(self, **kwargs):
        super().__init__(pull_duration=1, **kwargs)

    def _run(self, start, end, transformed_documents, state, **other_documents):
        return []


class DecoratedUnsupervisedAnalytic(Analytic):
    """An unsupervised analytic used to exercise the decorator."""

    def __init__(self, **kwargs):
        super().__init__(pull_duration=1, **kwargs)

    def _run(self, start, end, transformed_documents, state, **other_documents):
        return []

    @classmethod
    def requires_fit(cls) -> bool:
        return False


def test_from_class_reads_defaults_from_the_analytic():
    spec = AnalyticSpec.from_class(DecoratedSupervisedAnalytic, key="decorated")

    assert spec.key == "decorated"
    assert spec.class_path.endswith("DecoratedSupervisedAnalytic")
    assert spec.requires_fit is True
    # The docstring (no How: block) becomes the summary via lead-text fallback.
    assert "supervised analytic" in spec.summary


def test_from_class_honors_explicit_overrides():
    spec = AnalyticSpec.from_class(
        DecoratedUnsupervisedAnalytic,
        key="decorated",
        family="network_anomalies",
        display_name="Decorated",
    )

    assert spec.requires_fit is False
    assert spec.family == "network_anomalies"
    assert spec.display_name == "Decorated"


def test_from_class_rejects_non_analytic_targets():
    class NotAnalytic:
        pass

    with pytest.raises(AnalyticSpecValidationError, match="Analytic subclass"):
        AnalyticSpec.from_class(NotAnalytic, key="bad")


def test_from_class_rejects_empty_key():
    with pytest.raises(AnalyticSpecValidationError, match="non-empty string key"):
        AnalyticSpec.from_class(DecoratedSupervisedAnalytic, key="")


def test_register_analytic_registers_and_returns_class():
    returned = register_analytic(
        key="decorated", family="network_anomalies"
    )(DecoratedSupervisedAnalytic)

    # The class is returned unchanged so the decorator is transparent.
    assert returned is DecoratedSupervisedAnalytic

    spec = get_analytic_spec("decorated")
    assert spec.family == "network_anomalies"
    assert spec.class_path.endswith("DecoratedSupervisedAnalytic")


def test_register_analytic_carries_capability_slots():
    sentinel = object()
    register_analytic(key="decorated", data_source=sentinel)(
        DecoratedSupervisedAnalytic
    )

    assert get_analytic_spec("decorated").data_source is sentinel


def test_register_analytic_rejects_duplicate_keys_by_default():
    register_analytic(key="decorated")(DecoratedSupervisedAnalytic)

    with pytest.raises(AnalyticRegistryError):
        register_analytic(key="decorated")(DecoratedUnsupervisedAnalytic)


def test_register_analytic_replace_allows_reregistration():
    register_analytic(key="decorated")(DecoratedSupervisedAnalytic)
    register_analytic(key="decorated", replace=True)(
        DecoratedUnsupervisedAnalytic
    )

    assert get_analytic_spec("decorated").requires_fit is False


# --- entry-point discovery ----------------------------------------------------


def test_discover_analytics_runs_callable_entry_points(monkeypatch):
    calls = {"n": 0}

    def _factory():
        calls["n"] += 1
        register_analytic(key="discovered")(DecoratedSupervisedAnalytic)

    class _FakeEntryPoint:
        name = "fake"

        def load(self):
            return _factory

    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda group: [_FakeEntryPoint()],
    )

    specs = discover_analytics()

    assert calls["n"] == 1
    assert any(spec.key == "discovered" for spec in specs)


def test_discover_analytics_skips_failing_entry_points(monkeypatch):
    class _BadEntryPoint:
        name = "bad"

        def load(self):
            raise RuntimeError("boom")

    class _GoodEntryPoint:
        name = "good"

        def load(self):
            def _factory():
                register_analytic(key="ok")(DecoratedSupervisedAnalytic)

            return _factory

    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda group: [_BadEntryPoint(), _GoodEntryPoint()],
    )

    specs = discover_analytics()

    # The bad entry point is skipped; the good one still registers.
    assert any(spec.key == "ok" for spec in specs)


# --- typed metadata promoted from docstrings ----------------------------------


class DocumentedAnalytic(Analytic):
    """
    Name: DocumentedAnalytic

    How: Detects a documented condition using a clear rule.

    When: Whenever the condition might occur.

    Mitre-Techniques:
        + Network Sniffing (T1040)

    Purdue-Levels:
        + level 2

    Tags:
        + example
        + documented
    """

    def __init__(self, **kwargs):
        super().__init__(pull_duration=1, **kwargs)

    def _run(self, start, end, transformed_documents, state, **other_documents):
        return []

    @classmethod
    def requires_fit(cls) -> bool:
        return False


def test_from_class_promotes_docstring_metadata_to_typed_fields():
    spec = AnalyticSpec.from_class(DocumentedAnalytic, key="documented")

    assert spec.summary.startswith("Detects a documented condition")
    assert spec.detection_logic.startswith("Detects a documented condition")
    assert spec.mitre_techniques == ["T1040"]
    assert spec.purdue_levels == [2]
    assert spec.labels == ["example", "documented"]


def test_register_analytic_overrides_win_over_docstring_metadata():
    register_analytic(
        key="documented",
        summary="Overridden summary",
        labels=["curated"],
    )(DocumentedAnalytic)

    spec = get_analytic_spec("documented")
    assert spec.summary == "Overridden summary"
    assert spec.labels == ["curated"]
    # Fields not overridden still come from the docstring.
    assert spec.mitre_techniques == ["T1040"]
