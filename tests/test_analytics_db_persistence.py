"""Tests for the GUI database-backed artifact store (:class:`DbArtifactStore`).

``build_fields`` is exercised directly (pure serialisation, no DB). The ORM
``save``/``load``/``exists``/``delete`` paths run against the pytest-django test
database via ``@pytest.mark.django_db``.
"""

import pytest

from parseus.analytics.persistence import (
    ARTIFACT_SCHEMA_VERSION,
    ArtifactNotFoundError,
    load_state_bytes,
)
from parseus.webapp.analytics.models import TrainedModel
from parseus.webapp.analytics.persistence import DbArtifactStore


def test_build_fields_produces_blob_and_plaintext_manifest():
    store = DbArtifactStore()
    state = {"training_set_": {1, 2, 3}, "threshold_": 4.5}

    fields = store.build_fields(state, analytic_class="pkg.mod.MyAnalytic")

    # Manifest is a plain dict (stored as JSONField), inspectable without loading.
    assert fields["manifest"]["schema_version"] == ARTIFACT_SCHEMA_VERSION
    assert fields["manifest"]["analytic_class"] == "pkg.mod.MyAnalytic"

    # State is opaque bytes that round-trip through the shared helper.
    assert isinstance(fields["artifact"], bytes)
    assert load_state_bytes(fields["artifact"]) == state


@pytest.mark.django_db
def test_save_updates_existing_row_and_load_round_trips():
    row = TrainedModel.objects.create(name="m", family="f", artifact=b"")
    store = DbArtifactStore()
    state = {"training_set_": {1, 2, 3}, "threshold_": 4.5}

    manifest = store.save(str(row.pk), state, analytic_class="pkg.mod.MyAnalytic")

    assert manifest["analytic_class"] == "pkg.mod.MyAnalytic"
    assert store.load(str(row.pk)) == state
    # The plaintext manifest is readable without deserialising the blob.
    assert store.load_manifest(str(row.pk))["schema_version"] == ARTIFACT_SCHEMA_VERSION


@pytest.mark.django_db
def test_load_from_instance_matches_load_by_key():
    row = TrainedModel.objects.create(name="m", family="f", artifact=b"")
    store = DbArtifactStore()
    state = {"threshold_": 1.0}
    store.save(str(row.pk), state, analytic_class="pkg.mod.MyAnalytic")

    row.refresh_from_db()
    assert store.load_from_instance(row) == state


@pytest.mark.django_db
def test_exists_and_delete():
    row = TrainedModel.objects.create(name="m", family="f", artifact=b"")
    store = DbArtifactStore()

    assert store.exists(str(row.pk)) is True
    store.delete(str(row.pk))
    assert store.exists(str(row.pk)) is False


@pytest.mark.django_db
def test_save_missing_row_raises():
    store = DbArtifactStore()
    with pytest.raises(ArtifactNotFoundError):
        store.save("999999", {"x": 1}, analytic_class="pkg.mod.MyAnalytic")


@pytest.mark.django_db
def test_load_missing_row_raises():
    store = DbArtifactStore()
    with pytest.raises(ArtifactNotFoundError):
        store.load("999999")
