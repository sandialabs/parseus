"""ORM round-trip tests for run-to-run state columns (pytest-django).

The suppression/dedup state lives in JSON columns: ``TrainedModel.run_state``
(supervised GUI predict) and ``AnalyticUserInput.run_state`` (unsupervised GUI
predict). These confirm the columns read/write and preserve the shape the
StateStore produces, and that ``source_config``/``suppression`` round-trip.
"""

import pytest

from parseus.webapp.analytics.models import AnalyticUserInput, TrainedModel


@pytest.mark.django_db
def test_trained_model_run_state_defaults_empty_and_round_trips():
    model = TrainedModel.objects.create(name="m", family="f", artifact=b"")
    # Defaults to an empty dict.
    assert TrainedModel.objects.get(pk=model.pk).run_state == {}

    state = {"_suppression_emissions": {"abc": "2024-01-01T00:00:00+00:00"}}
    model.run_state = state
    model.save(update_fields=["run_state"])

    assert TrainedModel.objects.get(pk=model.pk).run_state == state


@pytest.mark.django_db
def test_analytic_user_input_run_state_round_trips():
    ui = AnalyticUserInput.objects.create()
    assert AnalyticUserInput.objects.get(pk=ui.pk).run_state == {}

    state = {"seen": ["a", "b"]}
    ui.run_state = state
    ui.save(update_fields=["run_state"])

    assert AnalyticUserInput.objects.get(pk=ui.pk).run_state == state


@pytest.mark.django_db
def test_analytic_user_input_suppression_and_source_config_round_trip():
    ui = AnalyticUserInput.objects.create(
        run_idx_name="idx",
        suppression="24h",
        source_config={"schedule": 60, "pull_duration": 90},
    )
    fetched = AnalyticUserInput.objects.get(pk=ui.pk)
    assert fetched.suppression == "24h"
    assert fetched.source_config == {"schedule": 60, "pull_duration": 90}
