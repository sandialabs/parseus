"""Shared construction of ECS-shaped analytic alert documents.

Every analytic emits alert/event documents that follow the Elastic Common
Schema (ECS): a top-level ``@timestamp`` plus an ``event`` object carrying
``action``, ``category``, ``kind``, ``original`` and ``riskscore``. Historically
each analytic hand-built that skeleton, which drifted (e.g. ``event.category``
was sometimes a bare string instead of the ECS-required array).

:func:`build_ecs_alert` centralizes the skeleton so every alert is shaped
consistently. Analytic-specific context (``source``, ``destination``,
``network``, per-protocol blocks, ...) is merged in at the top level by the
caller.
"""

from datetime import datetime, timezone
from typing import Any, Optional, Union

__all__ = ["build_ecs_alert", "build_ecs_baseline"]

# Sentinel so an explicitly passed ``timestamp=None`` is preserved, while an
# omitted timestamp defaults to ``datetime.now(timezone.utc)``.
_UNSET = object()


def build_ecs_alert(
    action: str,
    original: Optional[str],
    riskscore: float,
    *,
    category: Union[str, list[str]] = "network",
    kind: str = "alert",
    timestamp: Any = _UNSET,
    event_extra: Optional[dict[str, Any]] = None,
    **top_level: Any,
) -> dict[str, Any]:
    """Build an ECS-shaped alert document.

    :param action: ECS ``event.action`` (e.g. ``"new function code"``).
    :param original: ECS ``event.original`` -- the human-readable description.
        Pass ``None`` to omit ``event.original`` entirely.
    :param riskscore: ECS ``event.riskscore``.
    :param category: ECS ``event.category``. Accepts a string or a list and is
        always stored as a list (``"network"`` -> ``["network"]``), matching the
        ECS keyword-array contract.
    :param kind: ECS ``event.kind`` (``"alert"`` for detections, ``"state"`` for
        baselines).
    :param timestamp: Value for the top-level ``@timestamp``. When omitted,
        ``datetime.now(timezone.utc)`` is used; an explicit value (including
        ``None``) is stored as-is.
    :param event_extra: Additional keys merged into the ``event`` object
        (e.g. ``created``, ``time``, ``command``).
    :param top_level: Additional top-level keys merged into the alert
        (e.g. ``source``, ``destination``, ``network`` or a per-protocol block).
    :return: The assembled alert dictionary.
    """
    if isinstance(category, str):
        category = [category]
    else:
        category = list(category)

    event: dict[str, Any] = {
        "action": action,
        "category": category,
        "kind": kind,
        "riskscore": riskscore,
    }
    if original is not None:
        event["original"] = original
    if event_extra:
        event.update(event_extra)

    alert: dict[str, Any] = {
        "@timestamp": datetime.now(timezone.utc) if timestamp is _UNSET else timestamp,
        "event": event,
    }
    alert.update(top_level)
    return alert


def build_ecs_baseline(
    original: str,
    *,
    category: Union[str, list[str]] = "network",
    timestamp: Any = _UNSET,
    event_extra: Optional[dict[str, Any]] = None,
    **top_level: Any,
) -> dict[str, Any]:
    """Build a baseline ("state") ECS document.

    A thin wrapper over :func:`build_ecs_alert` for the recurring baseline shape:
    ``action="baseline"``, ``kind="state"`` and ``riskscore=0.0``.
    """
    return build_ecs_alert(
        action="baseline",
        original=original,
        riskscore=0.0,
        category=category,
        kind="state",
        timestamp=timestamp,
        event_extra=event_extra,
        **top_level,
    )
