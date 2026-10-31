"""Tests for base analytic behavior."""

import logging
from datetime import datetime
from uuid import UUID

import pytest

from parseus.analytics.base import Analytic, AnalyticContractError


class MinimalAnalytic(Analytic):
    """Analytic test double that returns one alert."""

    def __init__(self):
        super().__init__(pull_duration=1)

    def _run(self, start, end, transformed_documents, state, **other_documents):
        return [{"event": {"kind": "alert"}}]


class GeneratorAnalytic(MinimalAnalytic):
    """Analytic test double that returns alerts lazily."""

    def _run(self, start, end, transformed_documents, state, **other_documents):
        yield {"event": {"kind": "alert"}}


class NoneAlertAnalytic(MinimalAnalytic):
    """Analytic test double that violates the alert return contract."""

    def _run(self, start, end, transformed_documents, state, **other_documents):
        return None


class SingleDictAlertAnalytic(MinimalAnalytic):
    """Analytic test double that returns one alert without wrapping it in a list."""

    def _run(self, start, end, transformed_documents, state, **other_documents):
        return {"event": {"kind": "alert"}}


class NonDictAlertAnalytic(MinimalAnalytic):
    """Analytic test double that returns a malformed alert item."""

    def _run(self, start, end, transformed_documents, state, **other_documents):
        return ["not-an-alert"]


class MissingFitAnalytic(Analytic):
    """Analytic test double that requires fit but does not implement it."""

    def __init__(self):
        super().__init__(pull_duration=1)

    def _run(self, start, end, transformed_documents, state, **other_documents):
        return []


class UnsupervisedMissingFitAnalytic(MissingFitAnalytic):
    """Analytic test double that does not require fit."""

    @classmethod
    def requires_fit(cls) -> bool:
        return False


class BaseHelperAnalytic(Analytic):
    """Minimal concrete analytic for exercising base helper methods.

    ``Analytic`` is abstract (``_run`` is an ``@abc.abstractmethod``), so base
    behaviour that does not depend on a real ``_run`` is tested through this
    smallest possible concrete subclass rather than the abstract base itself.
    """

    def __init__(self, pull_duration=1, log=None):
        super().__init__(pull_duration=pull_duration, log=log)

    def _run(self, start, end, transformed_documents, state, **other_documents):
        return []


def test_abstract_analytic_cannot_be_instantiated():
    # _run is an abstract method, so a bare Analytic is not instantiable and a
    # concrete subclass that omits _run is rejected at instantiation time.
    with pytest.raises(TypeError):
        Analytic(pull_duration=1)


def test_analytic_uses_provided_logger():
    logger = logging.getLogger("parseus.tests.analytics")

    analytic = BaseHelperAnalytic(pull_duration=1, log=logger)

    assert analytic._log is logger


def test_analytic_data_source_defaults_to_none_when_unregistered():
    analytic = BaseHelperAnalytic(pull_duration=1)

    # An unregistered analytic has no descriptor, so it declares no source.
    assert analytic.data_source() is None


def test_fit_requires_supervised_analytics_to_implement_fit_hook():
    analytic = MissingFitAnalytic()

    with pytest.raises(NotImplementedError, match="does not implement _fit"):
        analytic.fit([])


def test_fit_allows_missing_fit_hook_for_unsupervised_analytics():
    analytic = UnsupervisedMissingFitAnalytic()

    analytic.fit([])


def test_run_on_data_adds_common_fields_to_alerts():
    analytic = MinimalAnalytic()

    alerts = analytic.run_on_data([], start=None, end=None)

    assert alerts[0]["agent"]["type"] == "MinimalAnalytic"
    assert alerts[0]["acknowledge"]["reason"] == "none"
    assert "created" in alerts[0]["event"]
    assert "uuid" in alerts[0]["event"]


def test_run_on_data_normalizes_generator_alerts():
    analytic = GeneratorAnalytic()

    alerts = analytic.run_on_data([], start=None, end=None)

    assert isinstance(alerts, list)
    assert len(alerts) == 1
    assert alerts[0]["agent"]["type"] == "GeneratorAnalytic"


@pytest.mark.parametrize(
    "analytic, message",
    [
        (NoneAlertAnalytic(), "returned None"),
        (SingleDictAlertAnalytic(), "single dictionary"),
        (NonDictAlertAnalytic(), "expected dict"),
    ],
)
def test_run_on_data_rejects_invalid_alert_return_values(analytic, message):
    with pytest.raises(AnalyticContractError, match=message):
        analytic.run_on_data([], start=None, end=None)


def test_add_common_fields_to_alerts_adds_missing_common_fields():
    analytic = BaseHelperAnalytic(pull_duration=1)
    alerts = [{"event": {"kind": "alert"}}]

    analytic.add_common_fields_to_alerts(alerts)

    assert alerts[0]["agent"]["type"] == "BaseHelperAnalytic"
    assert alerts[0]["acknowledge"]["reason"] == "none"
    assert isinstance(alerts[0]["acknowledge"]["timestamp"], datetime)
    assert isinstance(alerts[0]["event"]["created"], datetime)
    assert isinstance(alerts[0]["event"]["uuid"], UUID)
    assert alerts[0]["event"]["kind"] == "alert"


def test_add_common_fields_to_alerts_preserves_existing_common_fields():
    analytic = BaseHelperAnalytic(pull_duration=1)
    created = datetime(2024, 1, 1)
    acknowledged = datetime(2024, 1, 2)
    event_uuid = UUID("00000000-0000-0000-0000-000000000001")
    alerts = [
        {
            "agent": {"type": "ExistingAnalytic"},
            "acknowledge": {
                "reason": "reviewed",
                "timestamp": acknowledged,
            },
            "event": {
                "created": created,
                "kind": "alert",
                "uuid": event_uuid,
            },
        }
    ]

    analytic.add_common_fields_to_alerts(alerts)
    analytic.add_common_fields_to_alerts(alerts)

    assert alerts[0]["agent"]["type"] == "ExistingAnalytic"
    assert alerts[0]["acknowledge"]["reason"] == "reviewed"
    assert alerts[0]["acknowledge"]["timestamp"] == acknowledged
    assert alerts[0]["event"]["created"] == created
    assert alerts[0]["event"]["uuid"] == event_uuid
    assert alerts[0]["event"]["kind"] == "alert"
