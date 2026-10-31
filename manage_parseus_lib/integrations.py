from __future__ import annotations

from typing import List, Optional

from manage_parseus_lib.constants import AVAILABLE_INTEGRATIONS
from manage_parseus_lib.output import die

def parse_integrations_value(raw: Optional[str], source: str) -> Optional[List[str]]:
    if raw is None:
        return None

    raw = raw.strip().lower()
    if raw == "":
        return []

    chosen = [x.strip() for x in raw.split(",") if x.strip()]
    return normalize_integrations(chosen, source=source)

def normalize_integrations(values: object, source: str) -> List[str]:
    if not isinstance(values, list):
        die(f"Invalid integrations from {source}: expected a list")

    chosen = []
    for value in values:
        if not isinstance(value, str):
            die(f"Invalid integrations from {source}: expected string values")
        cleaned = value.strip().lower()
        if cleaned:
            chosen.append(cleaned)

    unknown = sorted(set(chosen) - AVAILABLE_INTEGRATIONS)
    if unknown:
        die(
            f"Unknown option(s) from {source}: {', '.join(unknown)}. "
            f"Valid options: {', '.join(sorted(AVAILABLE_INTEGRATIONS))}"
        )

    seen = set()
    result = []
    for x in chosen:
        if x not in seen:
            seen.add(x)
            result.append(x)
    return result

