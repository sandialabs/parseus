from __future__ import annotations

import argparse
import shutil
from typing import Dict, List, Optional

from manage_parseus_lib.commands.uninstall import is_uninstallable
from manage_parseus_lib.constants import DEFAULT_CMD_TIMEOUT
from manage_parseus_lib.docker.compose import compose_runtime_cmd
from manage_parseus_lib.install.paths import (
    InstallPaths,
    has_complete_install_state,
    has_runtime_install_markers,
    is_installed,
)
from manage_parseus_lib.formatting import format_list
from manage_parseus_lib.integrations import normalize_integrations
from manage_parseus_lib.output import die, info, warn
from manage_parseus_lib.process import run
from manage_parseus_lib.state.manifest import load_manifest, manifest_integrations_value
from manage_parseus_lib.system.health import port_is_available
from manage_parseus_lib.system.preflight import require_admin_privileges
from manage_parseus_lib.system.accounts import ADMIN_GROUP
from manage_parseus_lib.system.systemd import systemd_status_facts
from manage_parseus_lib.workflows.integrations import resolve_status_integrations


def _load_status_manifest(install_paths: InstallPaths) -> Optional[dict]:
    """Load the install manifest for status display, degrading gracefully.

    Reading state files requires an active ``parseus-admin`` group session.
    ``require_admin_privileges`` already rejects users who are not in the group,
    but a filesystem-level PermissionError can still surface (for example a
    misconfigured directory mode). Translate it into an actionable message
    instead of leaking a raw traceback.
    """
    try:
        if not install_paths.current_manifest.exists():
            return None
        return load_manifest(install_paths.current_manifest)
    except PermissionError:
        die(
            "Cannot read the Parseus install manifest:\n"
            f"  {install_paths.current_manifest}\n"
            f"This requires an active {ADMIN_GROUP!r} group session. If you were "
            "just added to the group, start a new session for it to take effect:\n"
            f"  newgrp {ADMIN_GROUP}      # activate the group in a subshell\n"
            "  # or log out and back in, or run with sudo:\n"
            "Run: sudo manage-parseus status"
        )


def do_status(args: argparse.Namespace) -> None:
    context = args.deployment_context
    config = context.config
    install_paths = context.paths

    require_admin_privileges("status")
    manifest = _load_status_manifest(install_paths)

    print("\nParseus status")
    print("==============")
    print(f"Application root: {install_paths.app_root}")
    print(f"Configuration root: {install_paths.config_root}")
    print(f"State root: {install_paths.data_root}")
    print(f"Installed: {'yes' if is_installed(install_paths) else 'no'}")

    manifest_config = get_manifest_installer_config(manifest)
    public_url = str(manifest_config.get("public_url") or config.public_url)
    health_host = str(manifest_config.get("health_host") or config.health_host)
    health_port = int(manifest_config.get("https_port") or config.https_port)

    print(f"Public URL: {public_url}")
    print(f"Readiness endpoint: {health_host}:{health_port}")
    port_listening = not port_is_available(health_host, health_port)
    print(f"HTTPS port listening: {'yes' if port_listening else 'no'}")

    systemd_facts = systemd_status_facts()
    if systemd_facts is not None:
        print(f"Boot-enabled (systemd): {systemd_facts['enabled']}")
        print(f"Service state (systemd): {systemd_facts['active']}")

    if has_complete_install_state(install_paths):
        print("Installation state: complete")
    elif has_runtime_install_markers(install_paths):
        print("Installation state: runtime markers present, manifest missing")
    elif is_uninstallable(install_paths):
        print("Installation state: partial install/state found")
    else:
        print("Installation state: none found")

    if manifest:
        print(f"Manifest: {install_paths.current_manifest}")
        print(f"Installed at: {manifest.get('installed_at', 'unknown')}")
        print(f"App version: {manifest.get('app_version', 'unknown')}")
        manifest_integrations = normalize_integrations(
            manifest_integrations_value(manifest), source="manifest"
        )
        print(f"Manifest integrations: {format_list(manifest_integrations)}")
        print(f"Manifest images: {len(manifest.get('all_images', []))}")

        method = manifest_config.get("method")
        if method:
            print(f"Install method: {method}")
        config_file = manifest_config.get("config_file")
        if config_file:
            print(f"Config file: {config_file}")
    else:
        print("Manifest: not found")

    compose_integrations, integrations_source = resolve_status_integrations(manifest, args)
    print(
        f"Compose status integrations: {format_list(compose_integrations)} "
        f"({integrations_source})"
    )
    show_compose_status_optional(install_paths, compose_integrations)


def get_manifest_installer_config(manifest: Optional[Dict]) -> Dict[str, object]:
    if not manifest:
        return {}
    value = manifest.get("installer_config", {})
    return value if isinstance(value, dict) else {}



def show_compose_status_optional(
    install_paths: InstallPaths, integrations: List[str]
) -> None:
    if not install_paths.images_compose.exists() or not install_paths.runtime_compose.exists():
        info("Compose files not found; skipping Docker Compose service status")
        return

    if shutil.which("docker") is None:
        warn("Docker CLI not found; skipping Docker Compose service status")
        return

    r = run(["docker", "compose", "version"], timeout=DEFAULT_CMD_TIMEOUT)
    if not r.ok:
        warn(
            "Docker Compose v2 is not available; skipping Docker Compose "
            f"service status: {r.stderr or r.stdout}"
        )
        return

    cmd = compose_runtime_cmd(install_paths, integrations) + ["ps"]
    r = run(cmd, timeout=DEFAULT_CMD_TIMEOUT)
    if not r.ok:
        warn(f"Could not read Docker Compose service status: {r.stderr or r.stdout}")
        return

    if r.stdout:
        print("\nDocker Compose services")
        print("-----------------------")
        print(r.stdout)
    else:
        info("Docker Compose returned no service status output")
