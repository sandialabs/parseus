from __future__ import annotations

from typing import Sequence


def format_list(values: Sequence[str]) -> str:
    """Format a list of CLI values for compact human-readable output."""
    return ",".join(values) if values else "none"
