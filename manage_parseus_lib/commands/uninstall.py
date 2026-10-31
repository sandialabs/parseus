from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from manage_parseus_lib.constants import UNINSTALL_REMOVABLE_VOLUMES
from manage_parseus_lib.docker.compose import bring_down_stack_if_possible
from manage_parseus_lib.docker.volumes import remove_named_volumes
from manage_parseus_lib.install.files import wrapper_points_to_target
from manage_parseus_lib.install.paths import InstallPaths, validate_system_managed_path
from manage_parseus_lib.integrations import normalize_integrations
from manage_parseus_lib.output import die, info, ok, warn
from manage_parseus_lib.state.manifest import (
    load_manifest,
    manifest_integrations_value,
    manifest_named_volumes_value,
    purge_manifest_images,
)
from manage_parseus_lib.system.accounts import remove_system_accounts
from manage_parseus_lib.system.preflight import preflight, require_root_for_system_install
from manage_parseus_lib.system.systemd import remove_systemd_unit


def do_uninstall(args: argparse.Namespace) -> None:
    context = args.deployment_context
    install_paths = context.paths

    require_root_for_system_install("uninstall")
    require_uninstallable(install_paths)
    preflight(require_openssl=False)

    manifest = load_manifest(install_paths.current_manifest)
    integrations = (
        normalize_integrations(manifest_integrations_value(manifest), source="manifest")
        if manifest
        else []
    )

    confirm_uninstall(manifest, args.keep_images, args.yes)

    remove_systemd_unit()
    bring_down_stack_if_possible(install_paths, integrations)
    remove_named_volumes(resolve_uninstall_volumes(manifest))
    remove_system_paths(install_paths, purge_ingest_drop=args.purge_ingest_drop)

    if args.remove_system_account:
        remove_system_accounts(manifest)

    if args.keep_images:
        info("Keeping Docker images recorded in manifest (--keep-images set)")
    else:
        purge_manifest_images(manifest)

    ok("Uninstall complete.")


def resolve_uninstall_volumes(manifest: Optional[Dict]) -> List[str]:
    if manifest:
        manifest_volumes = manifest_named_volumes_value(manifest)
        if manifest_volumes:
            info(f"Using Docker volumes recorded in manifest: {manifest_volumes}")
            return manifest_volumes

    warn(
        "Manifest does not record Docker volumes; falling back to legacy Parseus "
        "volume names. Review the list carefully before confirming uninstall."
    )
    return UNINSTALL_REMOVABLE_VOLUMES


def is_uninstallable(install_paths: InstallPaths) -> bool:
    markers = [
        install_paths.current_manifest,
        install_paths.runtime_compose,
        install_paths.images_compose,
        install_paths.state_dir,
        install_paths.env_dir,
        install_paths.certs_dir,
    ]
    return any(p.exists() for p in markers)


def require_uninstallable(install_paths: InstallPaths) -> None:
    if not is_uninstallable(install_paths):
        die(
            "Parseus does not appear to be installed.\n"
            "No installation markers were found."
        )


def confirm_uninstall(
    manifest: Optional[Dict], keep_images: bool, assume_yes: bool = False
) -> None:
    print("\nWARNING: This will completely remove Parseus from this system.")
    print("The following will be removed:")
    print("  - All Parseus containers")
    print("  - All Parseus container volumes and data")
    print("  - All generated environment/configuration files")
    print("  - All generated certificates")
    print("  - All installation state and manifest files")

    if keep_images:
        print(
            "  - Docker images recorded in the install manifest will be kept "
            "(--keep-images set)"
        )
    else:
        image_count = 0
        if manifest:
            resolved_images = manifest.get("resolved_images", {})
            image_count = len(set(v for v in resolved_images.values() if v))
        print(
            "  - Docker images recorded in the install manifest will also be "
            f"removed ({image_count} image(s))"
        )

    print("\nThis action cannot be undone.")

    if assume_yes:
        warn("Skipping uninstall confirmation because --yes was provided.")
        return

    raw = input("Type 'uninstall' to continue, or anything else to cancel: ").strip().lower()
    if raw != "uninstall":
        die("Uninstall cancelled by user.", rc=0)


def remove_system_paths(
    install_paths: InstallPaths,
    *,
    purge_ingest_drop: bool = False,
) -> None:
    info("Removing Parseus system directories...")

    remove_command_wrapper(install_paths)

    specs = [
        (install_paths.app_root, [install_paths.app_root / "manage_parseus.py", install_paths.app_root / "deploy"]),
        (install_paths.config_root, [install_paths.env_dir, install_paths.certs_dir, install_paths.compose_env_file]),
        (install_paths.data_root, [install_paths.current_manifest, install_paths.runtime_compose, install_paths.images_compose]),
        (install_paths.log_root, []),
    ]
    if purge_ingest_drop:
        specs.append((install_paths.drop_dir, []))
    else:
        info(f"Keeping ingest drop directory: {install_paths.drop_dir}")

    removed = False
    for root, markers in specs:
        if remove_managed_path(root, markers):
            removed = True

    if removed:
        ok("Files and directories removed.")
    else:
        info("No Parseus system directories were present")


def remove_command_wrapper(install_paths: InstallPaths) -> None:
    wrapper = install_paths.wrapper_path
    target = install_paths.app_root / "manage_parseus.py"

    if not wrapper.exists() and not wrapper.is_symlink():
        return
    if not wrapper.is_symlink():
        # A non-symlink wrapper is never removed. If the wrapper path is
        # misconfigured to point at the installed script itself, say so
        # explicitly instead of implying an unknown third-party file.
        if wrapper == target or wrapper.resolve(strict=False) == target.resolve(strict=False):
            info(
                "Command wrapper path resolves to the installed script; "
                f"leaving it in place: {wrapper}"
            )
        else:
            warn(f"Leaving non-symlink command wrapper in place: {wrapper}")
        return
    if not wrapper_points_to_target(wrapper, target):
        warn(f"Leaving non-Parseus command wrapper in place: {wrapper}")
        return

    info(f"Removing command wrapper: {wrapper}")
    wrapper.unlink()


def remove_managed_path(path: Path, markers: List[Path]) -> bool:
    validate_system_managed_path(path)
    if not path.exists():
        info(f"Path already absent: {path}")
        return False
    if not path.is_dir():
        die(f"Refusing to remove {path}: expected a directory")
    if markers and not any(marker.exists() for marker in markers):
        die(f"Refusing to remove {path}: expected Parseus markers not found")

    info(f"Removing Parseus path: {path}")
    shutil.rmtree(path)
    return True
