from __future__ import annotations

import argparse
from typing import Dict, List, Optional

from manage_parseus_lib.config.model import InstallerConfig
from manage_parseus_lib.docker.compose import bring_down_stack_if_possible, bring_up_stack
from manage_parseus_lib.install.env_files import ensure_compose_env_file
from manage_parseus_lib.install.paths import InstallPaths, require_installed
from manage_parseus_lib.integrations import normalize_integrations
from manage_parseus_lib.output import info, ok
from manage_parseus_lib.state.manifest import (
    build_install_manifest,
    load_manifest,
    manifest_integrations_value,
    manifests_differ_meaningfully,
    save_current_install_manifest,
)
from manage_parseus_lib.system.browser import maybe_open_browser
from manage_parseus_lib.system.preflight import preflight, require_admin_privileges
from manage_parseus_lib.system.systemd import (
    start_via_systemd,
    stop_via_systemd,
    write_systemd_integration_env,
)

from manage_parseus_lib.workflows.integrations import resolve_existing_install_integrations
from manage_parseus_lib.workflows.stack import (
    build_stack_plan,
    run_app_setup,
    verify_stack_plan,
    wait_for_stack_readiness,
)
from manage_parseus_lib.docker.compose import show_stack_status


def do_up(args: argparse.Namespace) -> None:
    context = args.deployment_context
    config = context.config
    install_paths = context.paths

    require_admin_privileges("up")
    require_installed(install_paths)

    preflight(require_openssl=False)
    old_manifest = load_manifest(install_paths.current_manifest)
    integrations = resolve_existing_install_integrations(old_manifest, args)

    # Compose never stops containers whose profile is no longer active, and the
    # oneshot systemd unit ignores a plain start while active. A changed
    # integration set therefore needs a full stop/start so the running stack
    # matches the requested integrations, including removals.
    previous = recorded_integrations(old_manifest)
    restart_required = previous is not None and set(previous) != set(integrations)
    if restart_required:
        info(
            f"Integrations changed from {previous} to {integrations}; "
            "restarting the full stack (core services will be briefly unavailable)..."
        )
        if not stop_via_systemd():
            bring_down_stack_if_possible(install_paths, previous)

    start_stack_and_maybe_update_manifest(
        install_paths,
        config,
        integrations,
        old_manifest,
        args.open_browser,
        (
            f"Parseus restarted with changed integrations. Integrations: {integrations}"
            if restart_required
            else f"Parseus started. Integrations: {integrations}"
        ),
        skip_port_check_when_running=not restart_required,
    )


def recorded_integrations(manifest: Optional[Dict]) -> Optional[List[str]]:
    """Return integrations recorded in the manifest, or None when there is no manifest."""
    if not manifest:
        return None
    return normalize_integrations(manifest_integrations_value(manifest), source="manifest")


def do_down(args: argparse.Namespace) -> None:
    install_paths = args.deployment_context.paths

    require_admin_privileges("down")
    require_installed(install_paths)

    preflight(require_openssl=False)

    manifest = load_manifest(install_paths.current_manifest)
    integrations = (
        normalize_integrations(manifest_integrations_value(manifest), source="manifest")
        if manifest
        else []
    )

    if not stop_via_systemd():
        bring_down_stack_if_possible(install_paths, integrations)
    ok("Parseus stopped.")


def do_restart(args: argparse.Namespace) -> None:
    context = args.deployment_context
    config = context.config
    install_paths = context.paths

    require_admin_privileges("restart")
    require_installed(install_paths)

    preflight(require_openssl=False)
    old_manifest = load_manifest(install_paths.current_manifest)
    integrations = resolve_existing_install_integrations(old_manifest, args)
    info("Stopping existing Parseus stack before restart...")
    if not stop_via_systemd():
        bring_down_stack_if_possible(install_paths, integrations)
    start_stack_and_maybe_update_manifest(
        install_paths,
        config,
        integrations,
        old_manifest,
        args.open_browser,
        f"Parseus restarted. Integrations: {integrations}",
    )


def start_stack_and_maybe_update_manifest(
    install_paths: InstallPaths,
    config: InstallerConfig,
    integrations: List[str],
    old_manifest: Optional[Dict],
    open_browser_requested: bool,
    success_message: str,
    skip_port_check_when_running: bool = False,
) -> None:
    ensure_compose_env_file(install_paths, config.compose_env)
    plan = build_stack_plan(install_paths, integrations)
    verify_stack_plan(
        install_paths,
        integrations,
        plan,
        skip_port_check_when_running=skip_port_check_when_running,
    )

    # Keep the resolved integration profiles in sync with the systemd unit's
    # EnvironmentFile before starting, then prefer systemd for the actual
    # start so the stack matches boot behavior. Falls back to driving Docker
    # Compose directly on hosts without systemd.
    write_systemd_integration_env(install_paths, integrations)
    run_app_setup(install_paths, integrations)
    if start_via_systemd():
        show_stack_status(install_paths, integrations)
    else:
        bring_up_stack(install_paths, integrations)
        show_stack_status(install_paths, integrations)

    new_manifest = build_install_manifest(
        plan.required_images,
        integrations,
        config,
        named_volumes=plan.named_volumes,
    )

    old_integrations = manifest_integrations_value(old_manifest) if old_manifest else []
    if manifests_differ_meaningfully(old_manifest, new_manifest):
        if sorted(set(old_integrations)) != sorted(set(integrations)):
            info(
                f"Effective integrations changed from {old_integrations} "
                f"to {integrations}; updating manifest"
            )
        else:
            info("Manifest drift detected; updating manifest")
        save_current_install_manifest(install_paths, new_manifest)
    else:
        info("Manifest already matches current configuration; no update needed")

    wait_for_stack_readiness(config)

    ok(success_message)
    maybe_open_browser(config.public_url, open_browser_requested)
