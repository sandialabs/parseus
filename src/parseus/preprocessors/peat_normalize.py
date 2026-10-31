"""Normalization helpers for PEAT filesystem analytic inputs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from parseus.util.datetime_utils import datetime_parser


def as_list(value: Any) -> list:
    """Return ``value`` as a list without treating strings as iterables."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, set):
        return list(value)
    return [value]


def file_identity_values(values: Any):
    """Yield stable string identities from PEAT file entries."""
    for item in as_list(values):
        if isinstance(item, dict):
            item = item.get("path") or item.get("name") or item.get("local_path")
        if item:
            yield str(item)


def entry_identity(item: Any, fallback: str) -> str:
    """Return a stable identity for a PEAT structured record."""
    if isinstance(item, dict):
        for key in ("id", "name", "address", "path", "tag", "protocol", "version"):
            value = item.get(key)
            if value:
                return str(value)
    return fallback


def mapping_by_identity(values: Any) -> dict[str, Any]:
    """Convert PEAT list-style records into a dictionary keyed by identity."""
    return {
        entry_identity(item, f"item-{index}"): item
        for index, item in enumerate(as_list(values))
    }


def normalize_record_mapping(records: Any) -> dict[str, Any]:
    """Return records as a mapping keyed by explicit names or record identity."""
    if isinstance(records, dict):
        return {str(key): value for key, value in records.items()}
    return mapping_by_identity(records)


def normalize_io_modules(value: Any) -> dict[str, dict[str, Any]]:
    """Return IO data in the module-category mapping expected by analytics."""
    if not value:
        return {}
    if isinstance(value, dict) and not any(
        identity_key in value for identity_key in ("id", "name", "address", "tag")
    ):
        return {
            str(category): normalize_record_mapping(records)
            for category, records in value.items()
        }
    mapped = mapping_by_identity(value)
    return {"IO Modules": mapped} if mapped else {}


def normalize_services(value: Any) -> list[dict[str, Any]]:
    """Return PEAT service records with required comparison fields populated."""
    services = []
    for record in as_list(value):
        if not isinstance(record, dict):
            continue
        normalized = dict(record)
        normalized.setdefault("protocol", "unknown")
        normalized.setdefault("port", None)
        normalized.setdefault("status", "unknown")
        services.append(normalized)
    return services


def normalize_firmware_logs(summary: dict[str, Any]) -> dict[str, list]:
    """Return PEAT firmware fields as log-name -> list[firmware record]."""
    logs = {}
    for key in ("firmware", "boot_firmware"):
        records = as_list(summary.get(key))
        records = [record for record in records if record]
        if records:
            logs[key] = records
    return logs


def normalize_process_memory(summary: dict[str, Any]) -> dict[str, Any]:
    """Return process-associated memory records keyed by process name."""
    processes = {}
    for index, record in enumerate(as_list(summary.get("memory"))):
        if not isinstance(record, dict):
            continue
        process = record.get("process")
        if not process:
            continue
        processes[str(process)] = record.get("value", record) or f"memory-{index}"
    return processes


def event_is_auth_failure(event: dict[str, Any]) -> bool:
    """Return whether a normalized PEAT event is an authentication failure."""
    if not isinstance(event, dict):
        return False

    outcome = str(event.get("outcome", "")).lower()
    category = event.get("category", [])
    category_values = {str(value).lower() for value in as_list(category)}
    text = " ".join(
        str(event.get(key, "")) for key in ("action", "message", "original")
    ).lower()

    return outcome == "failure" and (
        "authentication" in category_values
        or any(term in text for term in ("auth", "login", "access"))
    )


def event_timestamp(event: dict[str, Any]) -> datetime | None:
    """Return an event timestamp from normalized PEAT event records."""
    if not isinstance(event, dict):
        return None
    for key in ("created", "@timestamp", "timestamp", "ingested"):
        value = event.get(key)
        if not value:
            continue
        try:
            parsed = datetime_parser(value)
        except ValueError:
            continue
        if parsed and parsed.tzinfo is not None:
            return parsed.replace(tzinfo=None)
        return parsed
    return None


def event_cause_effect(event: dict[str, Any]) -> tuple | None:
    """Return useful context for authentication failure grouping."""
    if not isinstance(event, dict):
        return None
    cause_effect = (
        event.get("action"),
        event.get("outcome"),
        event.get("message") or event.get("original"),
    )
    return cause_effect if any(cause_effect) else None


def firmware_version_label(firmware_update: Any) -> str:
    """Return a stable, human-readable firmware version identifier."""
    if isinstance(firmware_update, dict):
        for key in ("firmware_version", "version", "revision", "id", "checksum"):
            value = firmware_update.get(key)
            if value:
                return str(value)
        hashes = firmware_update.get("hash") or {}
        if isinstance(hashes, dict):
            for key in ("sha256", "sha1", "md5"):
                if hashes.get(key):
                    return str(hashes[key])
    return str(firmware_update)
