from __future__ import annotations

import argparse
import re
from typing import Optional, Tuple

from manage_parseus_lib.constants import UPGRADE_REMOVABLE_VOLUME_SUFFIXES, UPGRADE_REMOVABLE_VOLUMES
from manage_parseus_lib.docker.compose import bring_down_stack_if_possible
from manage_parseus_lib.docker.images import prepare_images, verify_required_images
from manage_parseus_lib.docker.volumes import filter_volumes_by_suffix, remove_named_volumes
from manage_parseus_lib.install.certificates import uses_external_tls_certificates
from manage_parseus_lib.install.files import prepare_installation_files
from manage_parseus_lib.install.paths import require_installed, require_source_outside_install_root
from manage_parseus_lib.integrations import normalize_integrations
from manage_parseus_lib.output import die, info, ok, warn
from manage_parseus_lib.state.manifest import (
    build_install_manifest,
    load_manifest,
    manifest_integrations_value,
    manifest_named_volumes_value,
    remove_obsolete_manifest_images,
    save_current_install_manifest,
)
from manage_parseus_lib.system.browser import maybe_open_browser
from manage_parseus_lib.system.preflight import preflight, require_root_for_system_install
from manage_parseus_lib.system.systemd import (
    install_systemd_unit,
    start_via_systemd,
    stop_via_systemd,
)
from manage_parseus_lib.workflows.integrations import resolve_existing_install_integrations
from manage_parseus_lib.workflows.stack import (
    build_stack_plan,
    run_app_setup,
    verify_stack_plan,
    wait_for_stack_readiness,
)
from manage_parseus_lib.docker.compose import bring_up_stack, show_stack_status


VersionParts = Tuple[int, ...]


def parse_version_parts(value: object) -> Optional[VersionParts]:
    """Parse a comparable release version prefix, tolerating non-standard values."""
    text = str(value or "").strip()
    match = re.match(r"^v?(\d+(?:\.\d+)*)", text)
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def compare_version_parts(left: VersionParts, right: VersionParts) -> int:
    width = max(len(left), len(right))
    padded_left = left + (0,) * (width - len(left))
    padded_right = right + (0,) * (width - len(right))
    return (padded_left > padded_right) - (padded_left < padded_right)


def manifest_app_version(manifest) -> str:
    if not manifest:
        return "unknown"
    value = manifest.get("app_version")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "unknown"


def enforce_upgrade_version_policy(old_manifest, new_manifest, *, allow_downgrade: bool) -> None:
    old_version = manifest_app_version(old_manifest)
    new_version = manifest_app_version(new_manifest)
    info(f"Upgrading Parseus {old_version} -> {new_version}")

    old_parts = parse_version_parts(old_version)
    new_parts = parse_version_parts(new_version)
    if old_parts is None or new_parts is None:
        warn(
            "Could not compare Parseus versions for downgrade protection "
            f"(old={old_version!r}, new={new_version!r}); continuing."
        )
        return

    if compare_version_parts(new_parts, old_parts) < 0 and not allow_downgrade:
        die(
            f"Refusing to downgrade Parseus from {old_version} to {new_version}. "
            "Re-run with --allow-downgrade if this is intentional."
        )


def resolve_upgrade_removable_volumes(old_manifest) -> list[str]:
    manifest_volumes = manifest_named_volumes_value(old_manifest)
    selected = filter_volumes_by_suffix(
        manifest_volumes,
        UPGRADE_REMOVABLE_VOLUME_SUFFIXES,
    )
    if selected:
        info(f"Removing upgrade-scoped Docker volumes from manifest: {selected}")
        return selected

    info("No manifest-recorded upgrade volumes found; falling back to legacy volume names")
    return UPGRADE_REMOVABLE_VOLUMES


def do_upgrade(args: argparse.Namespace) -> None:
    context = args.deployment_context
    config = context.config
    install_paths = context.paths

    require_root_for_system_install("upgrade")
    require_installed(install_paths)
    require_source_outside_install_root(install_paths, "upgrade")
    preflight(require_openssl=not uses_external_tls_certificates(config))

    old_manifest = load_manifest(install_paths.current_manifest)
    if old_manifest:
        info("Existing Parseus manifest found; proceeding with upgrade")
    else:
        info("No existing manifest found; proceeding with upgrade using current installation files")

    integrations = resolve_existing_install_integrations(old_manifest, args)
    prepare_installation_files(install_paths, config=config, integrations=integrations)
    prepare_images(install_paths, config.method)

    plan = build_stack_plan(install_paths, integrations)
    verify_required_images(plan.required_images)

    new_manifest = build_install_manifest(
        plan.required_images,
        integrations,
        config,
        named_volumes=plan.named_volumes,
    )
    enforce_upgrade_version_policy(
        old_manifest,
        new_manifest,
        allow_downgrade=getattr(args, "allow_downgrade", False),
    )

    if old_manifest:
        info("Stopping existing Parseus stack before upgrade...")
        old_integrations = normalize_integrations(
            manifest_integrations_value(old_manifest), source="manifest"
        )
        if not stop_via_systemd():
            bring_down_stack_if_possible(install_paths, old_integrations)
        remove_named_volumes(resolve_upgrade_removable_volumes(old_manifest))

    verify_stack_plan(install_paths, integrations, plan, verify_images=False)

    # Refresh the systemd unit/env so paths and integration profiles match the
    # upgraded installation, then run pre-start setup and start via systemd
    # (falling back to direct Compose on hosts without systemd).
    install_systemd_unit(install_paths, integrations)
    run_app_setup(install_paths, integrations)
    if start_via_systemd():
        show_stack_status(install_paths, integrations)
    else:
        bring_up_stack(install_paths, integrations)
        show_stack_status(install_paths, integrations)

    save_current_install_manifest(install_paths, new_manifest)

    wait_for_stack_readiness(config, require_readiness=False)

    if args.keep_old_images:
        info("Keeping obsolete images from previous manifest (--keep-old-images set)")
    else:
        remove_obsolete_manifest_images(old_manifest, new_manifest)

    ok(f"Upgrade complete. Integrations: {integrations}")
    maybe_open_browser(config.public_url, args.open_browser)

