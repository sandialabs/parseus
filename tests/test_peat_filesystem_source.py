"""Tests for PEAT filesystem data source helpers."""

import json
from types import SimpleNamespace

from parseus.datastore.peat import PeatDocumentData
from parseus.datastore.sources import PeatFileDataSource, RunWindow
from parseus.preprocessors.peat_dir import (
    peat_device_transform,
    peat_file_transform,
    peat_io_transform,
    peat_service_transform,
)


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_peat_document_data_prefers_summary_identity_and_timestamp(tmp_path):
    device_dir = tmp_path / "devices" / "folder-name"
    _write_json(
        device_dir / "device-data-summary.json",
        {
            "ip": "192.0.2.10",
            "@timestamp": "2024-01-01T00:00:00Z",
            "related": {"files": ["config.txt"]},
        },
    )

    docs = PeatDocumentData(tmp_path)

    assert len(docs) == 1
    assert docs[0].device_id == "192.0.2.10"
    assert docs[0].path == device_dir
    assert peat_device_transform(docs) == {("192.0.2.10", docs[0].timestamp)}
    assert peat_file_transform(docs) == {
        "192.0.2.10": (docs[0].timestamp, {"config.txt"})
    }


def test_peat_document_data_skips_summaries_without_identity(tmp_path):
    device_dir = tmp_path / "devices" / "folder-name"
    _write_json(device_dir / "device-data-summary.json", {"service": []})

    docs = PeatDocumentData(tmp_path)

    assert len(docs) == 0


def test_peat_document_data_supports_summary_dirs_without_devices_folder(tmp_path):
    device_dir = tmp_path / "device-a"
    _write_json(
        device_dir / "device-data-summary.json",
        {"label": "plc-a", "related": {"files": ["logic.apx"]}},
    )
    (tmp_path / "logs").mkdir()

    docs = PeatDocumentData(tmp_path)

    assert [doc.device_id for doc in docs] == ["plc-a"]


def test_peat_transforms_use_normalized_summary_data(tmp_path):
    device_dir = tmp_path / "devices" / "plc-a"
    _write_json(
        device_dir / "device-data-summary.json",
        {
            "id": "plc-a",
            "service": [{"protocol": "modbus", "port": 502}],
            "io": [{"name": "input-1", "value": True}],
        },
    )

    docs = PeatDocumentData(tmp_path)

    assert peat_service_transform(docs) == {
        "plc-a": (
            docs[0].timestamp,
            [{"protocol": "modbus", "port": 502, "status": "unknown"}],
        )
    }
    assert peat_io_transform(docs) == {
        "plc-a": (
            docs[0].timestamp,
            {"IO Modules": {"input-1": {"name": "input-1", "value": True}}},
        )
    }


def test_peat_file_data_source_uses_single_snapshot_window():
    calls = []

    def fake_get_peat_data(path):
        calls.append(path)
        return ["peat-data"]

    config = SimpleNamespace(fit_idx="/fit", run_idx="/run", schedule=60)
    source = PeatFileDataSource(config, get_peat_data=fake_get_peat_data)

    assert source.get_fit_data(object()) == ["peat-data"]
    assert list(source.iter_run_windows(object())) == [RunWindow(start=None, end=None)]
    assert source.get_run_data(object(), RunWindow()) == ["peat-data"]
    assert calls == ["/fit", "/run"]
