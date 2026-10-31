from __future__ import annotations

import argparse
from typing import Dict, List, Optional, Tuple

from manage_parseus_lib.integrations import normalize_integrations, parse_integrations_value
from manage_parseus_lib.output import info
from manage_parseus_lib.state.manifest import manifest_integrations_value


def get_requested_integrations(args: argparse.Namespace) -> Tuple[Optional[List[str]], str]:
    """Return explicitly configured integrations and the source label for messages."""
    source = getattr(args, "integrations_source", "--integrations")
    return parse_integrations_value(args.integrations, source=source), source


def resolve_install_integrations(args: argparse.Namespace) -> List[str]:
    requested, source = get_requested_integrations(args)
    if requested is not None:
        info(f"Using integrations from {source}: {requested}")
        return requested

    info("No integrations configured; defaulting to no integrations")
    return []


def resolve_existing_install_integrations(
    old_manifest: Optional[Dict],
    args: argparse.Namespace,
) -> List[str]:
    requested, source = get_requested_integrations(args)
    if requested is not None:
        info(f"Using integrations from {source}: {requested}")
        return requested

    if old_manifest:
        integrations = normalize_integrations(
            manifest_integrations_value(old_manifest), source="manifest"
        )
        info(f"Reusing integrations from existing manifest: {integrations}")
        return integrations

    info("No --integrations provided and no manifest integrations found; defaulting to no integrations")
    return []


def resolve_status_integrations(
    manifest: Optional[Dict],
    args: argparse.Namespace,
) -> Tuple[List[str], str]:
    requested, source = get_requested_integrations(args)
    if requested is not None:
        return requested, source

    if manifest:
        return (
            normalize_integrations(manifest_integrations_value(manifest), source="manifest"),
            "manifest",
        )

    return [], "default"
