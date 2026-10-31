"""Redis-backed target locks for PEAT Celery jobs.

The PEAT CLI expands targets internally before scanning or pulling. This module
uses the same PEAT helpers for the target modes currently exposed by the webapp
so Parseus can lock concrete IP addresses and serial ports before queueing work.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import redis
from django.conf import settings
from peat.protocols.addresses import hosts_to_ips
from peat.protocols.serial import port_nums_to_addresses

LOGGER = logging.getLogger(__name__)

LOCK_PREFIX = "peat:lock"
OWNER_METADATA_PREFIX = "peat:lock-owner"

_ACQUIRE_LOCKS_SCRIPT = """
local owner = ARGV[1]
local ttl_seconds = tonumber(ARGV[2])
local metadata_key = ARGV[3]
local metadata_value = ARGV[4]

local busy = {}
for _, key in ipairs(KEYS) do
    local current_owner = redis.call("GET", key)
    if current_owner and current_owner ~= owner then
        table.insert(busy, key)
    end
end

if #busy > 0 then
    return busy
end

for _, key in ipairs(KEYS) do
    redis.call("SET", key, owner, "EX", ttl_seconds)
end
redis.call("SET", metadata_key, metadata_value, "EX", ttl_seconds)
return busy
"""

_RELEASE_LOCKS_SCRIPT = """
local owner = ARGV[1]
local metadata_key = ARGV[2]
local released = 0

for _, key in ipairs(KEYS) do
    if redis.call("GET", key) == owner then
        released = released + redis.call("DEL", key)
    end
end
redis.call("DEL", metadata_key)
return released
"""

_VERIFY_LOCKS_SCRIPT = """
local owner = ARGV[1]
local missing = {}

for _, key in ipairs(KEYS) do
    if redis.call("GET", key) ~= owner then
        table.insert(missing, key)
    end
end
return missing
"""

_REFRESH_LOCKS_SCRIPT = """
local owner = ARGV[1]
local ttl_seconds = tonumber(ARGV[2])
local metadata_key = ARGV[3]
local missing = {}

for _, key in ipairs(KEYS) do
    if redis.call("GET", key) ~= owner then
        table.insert(missing, key)
    end
end

if #missing > 0 then
    return missing
end

for _, key in ipairs(KEYS) do
    redis.call("EXPIRE", key, ttl_seconds)
end
if redis.call("EXISTS", metadata_key) == 1 then
    redis.call("EXPIRE", metadata_key, ttl_seconds)
else
    table.insert(missing, metadata_key)
end
return missing
"""


class PeatLockError(RuntimeError):
    """Raised when PEAT target locks cannot be resolved or managed."""


@dataclass(frozen=True)
class PeatLockTarget:
    """A concrete PEAT target and its Redis lock key."""

    target_mode: str
    target: str
    key: str


@dataclass(frozen=True)
class PeatLockAcquisition:
    """Result of an all-or-nothing target lock acquisition attempt."""

    acquired: bool
    owner: str
    target_mode: str
    targets: list[str]
    lock_keys: list[str]
    busy_targets: list[str]
    busy_lock_keys: list[str]


def get_redis_client() -> redis.Redis:
    """Return a Redis client using the configured Celery broker URL."""
    broker_url = getattr(settings, "CELERY_BROKER_URL", None)
    if not broker_url:
        raise PeatLockError("CELERY_BROKER_URL must be configured for PEAT locks")
    return redis.Redis.from_url(broker_url, decode_responses=True)


def get_lock_ttl_seconds() -> int:
    """Return the PEAT lock TTL in seconds."""
    ttl_seconds = int(getattr(settings, "PEAT_LOCK_TTL_SECONDS", 4 * 60 * 60))
    if ttl_seconds <= 0:
        raise PeatLockError("PEAT_LOCK_TTL_SECONDS must be greater than zero")
    return ttl_seconds


def build_owner_token(model_name: str, pk: int | str, task_id: str) -> str:
    """Build the owner token stored as the value of each Redis lock."""
    if not model_name or not pk or not task_id:
        raise PeatLockError("model_name, pk, and task_id are required for PEAT lock owner")
    return f"{model_name}:{pk}:{task_id}"


def build_owner_token_for_run(peat_run_obj) -> str:
    """Build an owner token for a saved PeatPull or PeatScan instance."""
    return build_owner_token(
        peat_run_obj.__class__.__name__, peat_run_obj.pk, peat_run_obj.task_id
    )


def metadata_key_for_owner(owner: str) -> str:
    """Return the Redis metadata key for a lock owner."""
    return f"{OWNER_METADATA_PREFIX}:{owner}"


def lock_key_for_target(target_mode: str, target: str) -> str:
    """Return the Redis lock key for a concrete PEAT target."""
    return f"{LOCK_PREFIX}:{target_mode}:{target}"


def _normalize_input_targets(targets: Iterable[str] | str) -> list[str]:
    """Return non-empty target strings while treating a string as one target."""
    if isinstance(targets, str):
        raw_targets = [targets]
    else:
        raw_targets = list(targets)
    return [str(target).strip() for target in raw_targets if str(target).strip()]


def resolve_lock_targets(targets: Iterable[str] | str, target_mode: str) -> list[PeatLockTarget]:
    """Resolve PEAT target input into concrete Redis lock targets.

    IP mode uses PEAT's ``hosts_to_ips()`` helper. Serial mode uses PEAT's
    ``port_nums_to_addresses()`` helper. Broadcast mode is intentionally not
    supported by the initial webapp locking implementation.
    """
    raw_targets = _normalize_input_targets(targets)
    if not raw_targets:
        raise PeatLockError("At least one PEAT target is required for locking")

    if target_mode == "ip":
        resolved_targets = hosts_to_ips(raw_targets)
    elif target_mode == "serial":
        resolved_targets = port_nums_to_addresses(raw_targets)
    else:
        raise PeatLockError(f"Unsupported PEAT target mode for locking: {target_mode}")

    resolved_targets = [
        str(target).strip() for target in resolved_targets if str(target).strip()
    ]
    if not resolved_targets:
        raise PeatLockError("No concrete PEAT targets could be resolved for locking")

    return [
        PeatLockTarget(
            target_mode=target_mode,
            target=target,
            key=lock_key_for_target(target_mode, target),
        )
        for target in resolved_targets
    ]


def _metadata_value(
    *,
    owner: str,
    target_mode: str,
    targets: list[str],
    lock_keys: list[str],
    ttl_seconds: int,
) -> str:
    """Build JSON metadata for a PEAT lock owner."""
    return json.dumps(
        {
            "owner": owner,
            "target_mode": target_mode,
            "targets": targets,
            "lock_keys": lock_keys,
            "ttl_seconds": ttl_seconds,
            "created_at": time.time(),
        },
        sort_keys=True,
    )


def get_owner_metadata(
    owner: str, *, client: redis.Redis | None = None
) -> dict[str, Any] | None:
    """Return stored lock metadata for an owner, if present and valid."""
    redis_client = client or get_redis_client()
    raw_metadata = redis_client.get(metadata_key_for_owner(owner))
    if not raw_metadata:
        return None
    try:
        metadata = json.loads(raw_metadata)
    except json.JSONDecodeError:
        LOGGER.warning("Invalid PEAT lock metadata for owner %s", owner)
        return None
    if not isinstance(metadata, dict) or metadata.get("owner") != owner:
        LOGGER.warning("Unexpected PEAT lock metadata for owner %s", owner)
        return None
    return metadata


def acquire_target_locks(
    *,
    owner: str,
    targets: Iterable[str] | str,
    target_mode: str,
    ttl_seconds: int | None = None,
    client: redis.Redis | None = None,
) -> PeatLockAcquisition:
    """Atomically acquire all concrete target locks for a PEAT run.

    If any requested lock is already owned by another run, no locks are
    acquired and the returned result contains the busy concrete targets.
    """
    ttl_seconds = ttl_seconds or get_lock_ttl_seconds()
    lock_targets = resolve_lock_targets(targets, target_mode)
    lock_keys = [target.key for target in lock_targets]
    resolved_targets = [target.target for target in lock_targets]
    target_by_key = {target.key: target.target for target in lock_targets}
    metadata_key = metadata_key_for_owner(owner)
    metadata_value = _metadata_value(
        owner=owner,
        target_mode=target_mode,
        targets=resolved_targets,
        lock_keys=lock_keys,
        ttl_seconds=ttl_seconds,
    )

    redis_client = client or get_redis_client()
    busy_lock_keys = redis_client.eval(
        _ACQUIRE_LOCKS_SCRIPT,
        len(lock_keys),
        *lock_keys,
        owner,
        ttl_seconds,
        metadata_key,
        metadata_value,
    )
    busy_lock_keys = [str(key) for key in busy_lock_keys]
    busy_targets = [target_by_key.get(key, key) for key in busy_lock_keys]

    acquired = not busy_lock_keys
    if acquired:
        LOGGER.info("Acquired %s PEAT target lock(s) for %s", len(lock_keys), owner)
    else:
        LOGGER.info("PEAT targets busy for %s: %s", owner, busy_targets)

    return PeatLockAcquisition(
        acquired=acquired,
        owner=owner,
        target_mode=target_mode,
        targets=resolved_targets,
        lock_keys=lock_keys,
        busy_targets=busy_targets,
        busy_lock_keys=busy_lock_keys,
    )


def release_target_locks(
    owner: str,
    lock_keys: Iterable[str],
    *,
    client: redis.Redis | None = None,
) -> int:
    """Release the provided locks only if they are still owned by ``owner``."""
    lock_key_list = [str(key) for key in lock_keys if str(key)]
    redis_client = client or get_redis_client()
    released = int(
        redis_client.eval(
            _RELEASE_LOCKS_SCRIPT,
            len(lock_key_list),
            *lock_key_list,
            owner,
            metadata_key_for_owner(owner),
        )
    )
    LOGGER.info("Released %s PEAT target lock(s) for %s", released, owner)
    return released


def release_owner_locks(owner: str, *, client: redis.Redis | None = None) -> int:
    """Release locks for an owner using Redis metadata."""
    redis_client = client or get_redis_client()
    metadata = get_owner_metadata(owner, client=redis_client)
    if not metadata:
        redis_client.delete(metadata_key_for_owner(owner))
        return 0
    return release_target_locks(owner, metadata.get("lock_keys") or [], client=redis_client)


def verify_target_locks(
    owner: str,
    lock_keys: Iterable[str] | None = None,
    *,
    client: redis.Redis | None = None,
) -> list[str]:
    """Return lock keys not currently owned by ``owner``.

    An empty list means ownership is valid for every requested lock. When
    ``lock_keys`` is omitted, the owner's Redis metadata is used.
    """
    redis_client = client or get_redis_client()
    if lock_keys is None:
        metadata = get_owner_metadata(owner, client=redis_client)
        if not metadata:
            return [metadata_key_for_owner(owner)]
        lock_keys = metadata.get("lock_keys") or []

    lock_key_list = [str(key) for key in lock_keys if str(key)]
    if not lock_key_list:
        return [metadata_key_for_owner(owner)]

    missing = redis_client.eval(
        _VERIFY_LOCKS_SCRIPT,
        len(lock_key_list),
        *lock_key_list,
        owner,
    )
    return [str(key) for key in missing]


def refresh_owner_locks(
    owner: str,
    *,
    ttl_seconds: int | None = None,
    client: redis.Redis | None = None,
) -> list[str]:
    """Extend the TTL for all locks owned by ``owner``.

    Returns lock keys that could not be refreshed because ownership was missing
    or changed. An empty list means every lock and the metadata key were
    refreshed successfully.
    """
    ttl_seconds = ttl_seconds or get_lock_ttl_seconds()
    redis_client = client or get_redis_client()
    metadata = get_owner_metadata(owner, client=redis_client)
    if not metadata:
        return [metadata_key_for_owner(owner)]

    lock_keys = [str(key) for key in metadata.get("lock_keys") or [] if str(key)]
    if not lock_keys:
        return [metadata_key_for_owner(owner)]

    missing = redis_client.eval(
        _REFRESH_LOCKS_SCRIPT,
        len(lock_keys),
        *lock_keys,
        owner,
        ttl_seconds,
        metadata_key_for_owner(owner),
    )
    return [str(key) for key in missing]


def owned_targets(owner: str, *, client: redis.Redis | None = None) -> list[str]:
    """Return the concrete targets recorded for an owner."""
    metadata = get_owner_metadata(owner, client=client)
    if not metadata:
        return []
    return [str(target) for target in metadata.get("targets") or []]
