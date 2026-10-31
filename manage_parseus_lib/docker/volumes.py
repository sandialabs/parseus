from __future__ import annotations

from typing import List

from manage_parseus_lib.constants import DEFAULT_CMD_TIMEOUT, LONG_CMD_TIMEOUT
from manage_parseus_lib.output import info, ok
from manage_parseus_lib.process import run


def docker_volume_exists(volume_name: str) -> bool:
    r = run(["docker", "volume", "inspect", volume_name], timeout=DEFAULT_CMD_TIMEOUT)
    return r.ok


def normalize_volume_names(volume_names: List[str]) -> List[str]:
    seen = set()
    unique = []
    for name in volume_names:
        name = name.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        unique.append(name)
    return unique


def filter_volumes_by_suffix(volume_names: List[str], suffixes: List[str]) -> List[str]:
    normalized_suffixes = tuple(suffix.strip() for suffix in suffixes if suffix.strip())
    if not normalized_suffixes:
        return []
    return [
        name
        for name in normalize_volume_names(volume_names)
        if any(name.endswith(suffix) for suffix in normalized_suffixes)
    ]


def remove_named_volumes(volume_names: List[str]) -> None:
    unique = normalize_volume_names(volume_names)
    if not unique:
        info("No Docker volumes selected for removal")
        return

    info(f"Removing {len(unique)} Docker volume(s)...")
    for volume_name in unique:
        if not docker_volume_exists(volume_name):
            info(f"Volume not found, skipping: {volume_name}")
            continue

        r = run(["docker", "volume", "rm", volume_name], timeout=LONG_CMD_TIMEOUT)
        if not r.ok:
            info(f"Could not remove volume {volume_name}: {r.stderr or r.stdout}")
        else:
            ok(f"Removed volume: {volume_name}")
