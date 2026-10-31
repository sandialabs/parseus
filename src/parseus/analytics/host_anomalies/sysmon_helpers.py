"""Helpers for Sysmon host anomaly analytics."""

from datetime import datetime, timezone


def nested_get(document: dict, path: str):
    """Return a nested value from a dotted path, or ``None`` if missing."""
    if path in document:
        return document[path]

    value = document
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def extract_timestamp_from_aggregation(doc):
    """
    Extract ``@timestamp`` from a composite aggregation bucket.

    Legacy Sysmon analytics used composite aggregations with a ``first_timestamp``
    top-hit sub-aggregation. Keep this helper so transforms remain backward
    compatible with already-tested aggregation-shaped inputs.
    """
    hits = doc.get("first_timestamp", {}).get("hits", {}).get("hits", {})
    first_document = list_get(hits, 0, {}).get("_source", {})
    return first_document.get("@timestamp", datetime.now(timezone.utc))


def list_get(lst, index, default=None):
    """Access a list's members returning a default if the index does not exist."""
    try:
        return lst[index]
    except IndexError:
        return default
