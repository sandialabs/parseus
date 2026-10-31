"""Tests for PEAT normalization helpers."""

from parseus.preprocessors.peat_normalize import (
    event_cause_effect,
    event_is_auth_failure,
    firmware_version_label,
    normalize_io_modules,
    normalize_services,
)


def test_normalize_services_populates_required_comparison_fields():
    services = normalize_services({"protocol": "modbus", "port": 502})

    assert services == [{"protocol": "modbus", "port": 502, "status": "unknown"}]


def test_normalize_io_modules_maps_list_records_by_identity():
    assert normalize_io_modules([{"name": "module-a", "value": 1}]) == {
        "IO Modules": {"module-a": {"name": "module-a", "value": 1}}
    }


def test_normalize_io_modules_maps_single_record_by_identity():
    assert normalize_io_modules({"name": "module-a", "value": 1}) == {
        "IO Modules": {"module-a": {"name": "module-a", "value": 1}}
    }


def test_normalize_io_modules_maps_category_records_by_identity():
    assert normalize_io_modules({"Inputs": [{"id": "in-1", "value": True}]}) == {
        "Inputs": {"in-1": {"id": "in-1", "value": True}}
    }


def test_normalize_io_modules_preserves_named_category_mappings():
    assert normalize_io_modules({"Inputs": {"in-1": {"value": True}}}) == {
        "Inputs": {"in-1": {"value": True}}
    }


def test_event_helpers_support_normalized_auth_failure_events():
    event = {
        "action": "login",
        "category": ["authentication"],
        "outcome": "failure",
        "message": "bad password",
    }

    assert event_is_auth_failure(event) is True
    assert event_cause_effect(event) == ("login", "failure", "bad password")


def test_firmware_version_label_uses_best_available_identity():
    assert firmware_version_label({"version": "1.2.3"}) == "1.2.3"
    assert firmware_version_label({"hash": {"sha256": "abc"}}) == "abc"
