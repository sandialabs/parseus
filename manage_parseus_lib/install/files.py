from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import List

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11; keep manage_parseus stdlib-only.
    tomllib = None

from manage_parseus_lib.config.model import InstallerConfig
from manage_parseus_lib.install.certificates import ensure_certs_dir, prepare_nginx_tls_certificates
from manage_parseus_lib.install.env_files import ensure_compose_env_file, ensure_env_dir, generate_env_files
from manage_parseus_lib.install.paths import InstallPaths, validate_system_managed_path
from manage_parseus_lib.output import die, info, ok
from manage_parseus_lib.system.permissions import set_app_bundle_permissions, set_runtime_file_permissions


def prepare_installation_files(
    install_paths: InstallPaths, config: InstallerConfig, integrations: List[str]
) -> None:
    copy_required_files(install_paths)
    ensure_env_dir(install_paths)
    ensure_certs_dir(install_paths)

    compose_env = build_compose_env(install_paths, config)
    ensure_compose_env_file(install_paths, compose_env)
    generate_env_files(
        install_paths,
        integrations=integrations,
        env_overrides=config.env_overrides,
        public_url=config.public_url,
    )
    prepare_nginx_tls_certificates(install_paths, config)


def build_compose_env(install_paths: InstallPaths, config: InstallerConfig) -> dict[str, str]:
    """Return Docker Compose environment values for this installation.

    ``manage_parseus`` is copied into deployment bundles and may run without the
    application package installed. Read the release version from the bundled
    ``pyproject.toml`` so repository installs and air-gapped bundles both feed
    the same ``PARSEUS_VERSION`` value into Docker Compose interpolation.
    """
    compose_env = dict(config.compose_env)
    compose_env.setdefault("PARSEUS_VERSION", read_project_version(install_paths.source_root))
    return compose_env


def read_project_version(source_root: Path) -> str:
    pyproject = source_root / "pyproject.toml"
    try:
        raw = pyproject.read_bytes()
    except OSError:
        return "dev"

    if tomllib is not None:
        try:
            version = tomllib.loads(raw.decode("utf-8")).get("project", {}).get("version")
        except Exception:
            version = None
        if isinstance(version, str) and version.strip():
            return version.strip()

    text = raw.decode("utf-8", errors="replace")
    match = re.search(r"""^version\s*=\s*["']([^"']+)["']\s*$""", text, re.MULTILINE)
    if match:
        return match.group(1)
    return "dev"


def copy_required_files(install_paths: InstallPaths) -> None:
    app_root = install_paths.app_root
    info(f"Copying application files to {app_root}...")
    validate_system_managed_path(app_root)
    app_root.mkdir(parents=True, exist_ok=True)

    src_dir = install_paths.source_root

    files_to_copy = [
        "README.md",
        "pyproject.toml",
        "nginx.conf",
        "entrypoint.sh",
        "manage_parseus.py",
    ]

    runtime_compose_files = {
        "compose.runtime.yaml": install_paths.runtime_compose,
        "compose.images.yaml": install_paths.images_compose,
    }

    dirs_to_copy = [
        "docs",
        "deploy",
        "manage_parseus_lib",
    ]

    for name in files_to_copy:
        src = src_dir / name
        dst = app_root / name
        if not src.exists() or not src.is_file():
            die(f"Required file missing from installer bundle: {src}")
        shutil.copy2(src, dst)
        set_app_bundle_permissions(dst)

    for name, dst in runtime_compose_files.items():
        src = src_dir / name
        if not src.exists() or not src.is_file():
            die(f"Required file missing from installer bundle: {src}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        set_runtime_file_permissions(dst)

    for name in dirs_to_copy:
        src = src_dir / name
        dst = app_root / name
        if not src.exists() or not src.is_dir():
            die(f"Required directory missing from installer bundle: {src}")
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        set_app_bundle_permissions(dst)

    set_app_bundle_permissions(app_root)
    install_command_wrapper(install_paths)
    ok(f"Copied application files to {app_root}")


def install_command_wrapper(install_paths: InstallPaths) -> None:
    target = install_paths.app_root / "manage_parseus.py"
    target.chmod(0o755)
    wrapper = install_paths.wrapper_path
    if wrapper.exists() or wrapper.is_symlink():
        if not wrapper.is_symlink() or not wrapper_points_to_target(wrapper, target):
            die(f"Refusing to overwrite non-Parseus command wrapper: {wrapper}")
        wrapper.unlink()

    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.symlink_to(target)
    ok(f"Installed command wrapper: {wrapper} -> {target}")


def wrapper_points_to_target(wrapper: Path, target: Path) -> bool:
    """Return True when a command-wrapper symlink resolves to the expected target."""
    try:
        link_target = Path(os.readlink(wrapper))
    except OSError:
        return False

    if not link_target.is_absolute():
        link_target = wrapper.parent / link_target

    return link_target.resolve(strict=False) == target.resolve(strict=False)
