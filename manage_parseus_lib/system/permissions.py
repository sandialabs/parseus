from __future__ import annotations

import os
import pwd
import grp
from dataclasses import dataclass
from pathlib import Path
from manage_parseus_lib.install.paths import InstallPaths
from manage_parseus_lib.output import die, ok
from manage_parseus_lib.system.accounts import ADMIN_GROUP, SERVICE_GROUP, SERVICE_USER

ROOT_UID = 0
ROOT_GID = 0
CONTAINER_WRITABLE_UID = 1000
CONTAINER_WRITABLE_GID = 1000


@dataclass(frozen=True)
class DirectorySpec:
    path: Path
    mode: int
    owner_uid: int
    owner_gid: int
    label: str


def provision_system_directories(install_paths: InstallPaths) -> None:
    """Create and verify the standard system-wide Parseus directory layout."""
    for spec in build_directory_specs(install_paths):
        ensure_directory_spec(spec)


def build_directory_specs(install_paths: InstallPaths) -> list[DirectorySpec]:
    service_uid = user_id(SERVICE_USER)
    service_gid = group_id(SERVICE_GROUP)
    admin_gid = group_id(ADMIN_GROUP)

    return [
        DirectorySpec(install_paths.app_root, 0o755, ROOT_UID, ROOT_GID, "application root"),
        DirectorySpec(install_paths.config_root, 0o750, ROOT_UID, admin_gid, "configuration root"),
        DirectorySpec(install_paths.env_dir, 0o750, ROOT_UID, admin_gid, "environment directory"),
        DirectorySpec(install_paths.certs_dir, 0o750, ROOT_UID, admin_gid, "certificate directory"),
        DirectorySpec(install_paths.data_root, 0o750, service_uid, admin_gid, "data root"),
        DirectorySpec(install_paths.state_dir, 0o750, service_uid, admin_gid, "state directory"),
        DirectorySpec(install_paths.history_dir, 0o750, service_uid, admin_gid, "manifest history directory"),
        DirectorySpec(install_paths.runtime_root, 0o750, service_uid, admin_gid, "runtime directory"),
        DirectorySpec(install_paths.winlog_logstash_state_dir, 0o750, CONTAINER_WRITABLE_UID, CONTAINER_WRITABLE_GID, "Winlog Logstash state directory"),
        DirectorySpec(install_paths.drop_dir, 0o750, CONTAINER_WRITABLE_UID, CONTAINER_WRITABLE_GID, "ingest drop directory"),
        DirectorySpec(install_paths.log_root, 0o750, service_uid, service_gid, "log root"),
    ]


def ensure_directory_spec(spec: DirectorySpec) -> None:
    try:
        spec.path.mkdir(parents=True, exist_ok=True)
        os.chown(spec.path, spec.owner_uid, spec.owner_gid)
        os.chmod(spec.path, spec.mode)
    except Exception as e:
        die(f"Failed to provision Parseus {spec.label} at {spec.path}: {e}")

    verify_directory_spec(spec)
    ok(f"Provisioned {spec.label}: {spec.path}")


def verify_directory_spec(spec: DirectorySpec) -> None:
    if not spec.path.exists():
        die(f"Parseus {spec.label} does not exist after provisioning: {spec.path}")
    if not spec.path.is_dir():
        die(f"Parseus {spec.label} is not a directory: {spec.path}")

    try:
        stat_result = spec.path.stat()
    except Exception as e:
        die(f"Could not inspect Parseus {spec.label} at {spec.path}: {e}")

    actual_mode = stat_result.st_mode & 0o777
    if stat_result.st_uid != spec.owner_uid or stat_result.st_gid != spec.owner_gid:
        die(
            f"Parseus {spec.label} has owner {stat_result.st_uid}:{stat_result.st_gid}; "
            f"expected {spec.owner_uid}:{spec.owner_gid}: {spec.path}"
        )
    if actual_mode != spec.mode:
        die(
            f"Parseus {spec.label} has mode {oct(actual_mode)}; "
            f"expected {oct(spec.mode)}: {spec.path}"
        )


def user_id(name: str) -> int:
    try:
        return pwd.getpwnam(name).pw_uid
    except KeyError:
        die(f"Required Parseus system user does not exist: {name}")


def set_config_file_permissions(path: Path, mode: int = 0o640) -> None:
    """Set standard ownership/mode for Parseus config files under /etc/parseus."""
    admin_gid = group_id(ADMIN_GROUP)
    try:
        os.chown(path, ROOT_UID, admin_gid)
        os.chmod(path, mode)
    except Exception as e:
        die(f"Failed to set Parseus config file permissions on {path}: {e}")


def set_app_bundle_permissions(path: Path) -> None:
    """Make installed application bundle files root-owned and not group/world-writable."""
    try:
        if path.is_dir():
            os.chown(path, ROOT_UID, ROOT_GID)
            os.chmod(path, 0o755)
            for child in path.rglob("*"):
                os.chown(child, ROOT_UID, ROOT_GID)
                if child.is_dir():
                    os.chmod(child, 0o755)
                else:
                    executable = child.stat().st_mode & 0o111
                    os.chmod(child, 0o755 if executable else 0o644)
        else:
            os.chown(path, ROOT_UID, ROOT_GID)
            executable = path.stat().st_mode & 0o111
            os.chmod(path, 0o755 if executable else 0o644)
    except Exception as e:
        die(f"Failed to set Parseus application bundle permissions on {path}: {e}")


def set_runtime_file_permissions(path: Path, mode: int = 0o644) -> None:
    """Set standard ownership/mode for generated runtime files under /var/lib/parseus."""
    service_gid = group_id(SERVICE_GROUP)
    try:
        os.chown(path, ROOT_UID, service_gid)
        os.chmod(path, mode)
    except Exception as e:
        die(f"Failed to set Parseus runtime file permissions on {path}: {e}")


def set_state_file_permissions(path: Path, mode: int = 0o640) -> None:
    """Set ownership/mode for installer state files under /var/lib/parseus/state.

    State files (the manifest and its history) are owned by the service user and
    the ``parseus-admin`` group so administrators can read installation state
    without root. They are not world-readable.
    """
    service_uid = user_id(SERVICE_USER)
    admin_gid = group_id(ADMIN_GROUP)
    try:
        os.chown(path, service_uid, admin_gid)
        os.chmod(path, mode)
    except Exception as e:
        die(f"Failed to set Parseus state file permissions on {path}: {e}")



def group_id(name: str) -> int:
    try:
        return grp.getgrnam(name).gr_gid
    except KeyError:
        die(f"Required Parseus system group does not exist: {name}")
