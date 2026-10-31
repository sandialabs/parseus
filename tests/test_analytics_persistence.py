"""Tests for the versioned artifact persistence layer and the file store."""

import json

import pytest

from parseus.analytics.persistence import (
    ARTIFACT_SCHEMA_VERSION,
    ArtifactFormatError,
    ArtifactNotFoundError,
    ArtifactVersionError,
    FileArtifactStore,
    build_manifest,
    dump_state_bytes,
    load_state_bytes,
    load_state_from_path,
    save_state_to_path,
    validate_manifest,
)


def test_manifest_carries_version_and_class():
    manifest = build_manifest("pkg.mod.MyAnalytic")

    assert manifest["schema_version"] == ARTIFACT_SCHEMA_VERSION
    assert manifest["analytic_class"] == "pkg.mod.MyAnalytic"
    assert "parseus_version" in manifest
    assert "created_at" in manifest


def test_validate_manifest_rejects_unknown_version():
    with pytest.raises(ArtifactVersionError):
        validate_manifest({"schema_version": ARTIFACT_SCHEMA_VERSION + 1})


def test_validate_manifest_rejects_non_mapping():
    with pytest.raises(ArtifactFormatError):
        validate_manifest(["not", "a", "mapping"])


def test_state_bytes_round_trip():
    state = {"training_set_": {1, 2, 3}, "threshold_": 4.5}

    assert load_state_bytes(dump_state_bytes(state)) == state


def test_load_state_bytes_rejects_non_mapping():
    blob = dump_state_bytes({"ok_": 1})
    # Re-serialise a non-mapping through joblib to exercise the guard.
    import io

    import joblib

    buf = io.BytesIO()
    joblib.dump([1, 2, 3], buf)
    with pytest.raises(ArtifactFormatError):
        load_state_bytes(buf.getvalue())
    # Sanity: the valid blob still loads.
    assert load_state_bytes(blob) == {"ok_": 1}


# ---------------------------------------------------------------------------
# FileArtifactStore
# ---------------------------------------------------------------------------


def test_file_store_writes_state_blob_and_plaintext_manifest(tmp_path):
    store = FileArtifactStore(tmp_path)
    state = {"training_set_": {1, 2, 3}}

    manifest = store.save("my_model", state, analytic_class="pkg.mod.MyAnalytic")

    # State blob exists and round-trips.
    assert store.exists("my_model")
    assert store.load("my_model") == state

    # Manifest is a readable JSON sidecar.
    manifest_path = tmp_path / "my_model.manifest.json"
    assert manifest_path.is_file()
    on_disk = json.loads(manifest_path.read_text())
    assert on_disk == manifest
    assert on_disk["analytic_class"] == "pkg.mod.MyAnalytic"
    assert store.load_manifest("my_model") == manifest


def test_file_store_missing_artifact_raises(tmp_path):
    store = FileArtifactStore(tmp_path)
    assert not store.exists("nope")
    with pytest.raises(ArtifactNotFoundError):
        store.load("nope")
    with pytest.raises(ArtifactNotFoundError):
        store.load_manifest("nope")


def test_file_store_delete_removes_both_files(tmp_path):
    store = FileArtifactStore(tmp_path)
    store.save("m", {"a_": 1}, analytic_class="pkg.mod.A")

    store.delete("m")

    assert not store.exists("m")
    assert not (tmp_path / "m.joblib").exists()
    assert not (tmp_path / "m.manifest.json").exists()
    # Deleting a missing key is a no-op.
    store.delete("m")


def test_file_store_load_rejects_unknown_schema_version(tmp_path):
    store = FileArtifactStore(tmp_path)
    store.save("m", {"a_": 1}, analytic_class="pkg.mod.A")
    # Corrupt the manifest to an unknown version.
    manifest_path = tmp_path / "m.manifest.json"
    manifest_path.write_text(json.dumps({"schema_version": ARTIFACT_SCHEMA_VERSION + 1}))

    with pytest.raises(ArtifactVersionError):
        store.load("m")


def test_path_wrappers_round_trip(tmp_path):
    path = tmp_path / "excess_conversation.joblib"
    state = {"stats_": [1, 2, 3], "load_window_": 5}

    save_state_to_path(str(path), state, analytic_class="pkg.mod.A")

    assert path.is_file()
    assert (tmp_path / "excess_conversation.manifest.json").is_file()
    assert load_state_from_path(str(path)) == state
