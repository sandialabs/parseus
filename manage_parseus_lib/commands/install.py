from __future__ import annotations

import argparse

from manage_parseus_lib.docker.images import prepare_images
from manage_parseus_lib.install.certificates import uses_external_tls_certificates
from manage_parseus_lib.install.files import prepare_installation_files
from manage_parseus_lib.install.paths import require_not_installed
from manage_parseus_lib.output import ok
from manage_parseus_lib.state.manifest import build_install_manifest, save_current_install_manifest
from manage_parseus_lib.system.accounts import ensure_system_accounts
from manage_parseus_lib.system.browser import maybe_open_browser
from manage_parseus_lib.system.permissions import provision_system_directories
from manage_parseus_lib.system.preflight import preflight, require_root_for_system_install
from manage_parseus_lib.system.systemd import install_systemd_unit, start_via_systemd
from manage_parseus_lib.workflows.integrations import resolve_install_integrations
from manage_parseus_lib.workflows.stack import (
    build_stack_plan,
    run_app_setup,
    verify_stack_plan,
    wait_for_stack_readiness,
)
from manage_parseus_lib.docker.compose import bring_up_stack, show_stack_status


def do_install(args: argparse.Namespace) -> None:
    context = args.deployment_context
    config = context.config
    install_paths = context.paths

    require_root_for_system_install("install")
    system_accounts = ensure_system_accounts()
    provision_system_directories(install_paths)
    require_not_installed(install_paths)
    preflight(require_openssl=not uses_external_tls_certificates(config))

    integrations = resolve_install_integrations(args)
    prepare_installation_files(install_paths, config=config, integrations=integrations)
    prepare_images(install_paths, config.method)

    plan = build_stack_plan(install_paths, integrations)
    verify_stack_plan(install_paths, integrations, plan)

    # Write and enable the systemd unit before first start so the initial
    # start matches boot behavior; fall back to direct Compose without systemd.
    install_systemd_unit(install_paths, integrations)
    run_app_setup(install_paths, integrations)
    if start_via_systemd():
        show_stack_status(install_paths, integrations)
    else:
        bring_up_stack(install_paths, integrations)
        show_stack_status(install_paths, integrations)

    manifest = build_install_manifest(
        plan.required_images,
        integrations,
        config,
        named_volumes=plan.named_volumes,
        system_accounts=system_accounts.as_manifest_data(),
    )
    save_current_install_manifest(install_paths, manifest)

    wait_for_stack_readiness(config, require_readiness=False)

    ok(f"Install complete. Integrations: {integrations}")
    maybe_open_browser(config.public_url, args.open_browser)

