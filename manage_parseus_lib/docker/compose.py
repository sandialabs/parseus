from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from manage_parseus_lib.constants import (
    DEFAULT_CMD_TIMEOUT,
    INTEGRATION_TO_COMPOSE_PROFILE,
    LONG_CMD_TIMEOUT,
)
from manage_parseus_lib.install.paths import InstallPaths
from manage_parseus_lib.output import die, info, ok
from manage_parseus_lib.process import run, run_streaming
from manage_parseus_lib.system.health import port_is_available
from manage_parseus_lib.system.permissions import CONTAINER_WRITABLE_GID, CONTAINER_WRITABLE_UID


def compose_base_cmd(project_name: Optional[str] = None) -> List[str]:
    cmd = ["docker", "compose"]
    if project_name:
        cmd += ["--project-name", project_name]
    return cmd


def build_compose_profile_args(integrations: List[str]) -> List[str]:
    profiles = []
    seen = set()
    for integration in integrations:
        profile = INTEGRATION_TO_COMPOSE_PROFILE.get(integration)
        if profile and profile not in seen:
            seen.add(profile)
            profiles.append(profile)

    args = []
    for profile in profiles:
        args += ["--profile", profile]
    return args


def compose_runtime_cmd(
    install_paths: InstallPaths, integrations: Optional[List[str]] = None
) -> List[str]:
    integrations = integrations or []
    return (
        compose_base_cmd(install_paths.project_name)
        + build_compose_profile_args(integrations)
        + compose_env_file_args(install_paths)
        + ["-f", str(install_paths.images_compose)]
        + ["-f", str(install_paths.runtime_compose)]
    )


def compose_env_file_args(install_paths: InstallPaths) -> List[str]:
    if install_paths.compose_env_file.exists():
        return ["--env-file", str(install_paths.compose_env_file)]
    return []


def bring_up_stack(install_paths: InstallPaths, integrations: List[str]) -> None:
    info("Bringing up Docker Compose stack (no-build, detached)...")
    cmd = compose_runtime_cmd(install_paths, integrations) + ["up", "--no-build", "-d"]
    r = run_streaming(
        cmd,
        timeout=LONG_CMD_TIMEOUT,
        heartbeat_message="Docker Compose startup is still running",
    )
    if not r.ok:
        die(
            f"Failed to start stack:\nCommand: {' '.join(cmd)}\n\n"
            f"{r.stderr or r.stdout}"
        )

    ok("Stack started")


def show_stack_status(install_paths: InstallPaths, integrations: List[str]) -> None:
    cmd = compose_runtime_cmd(install_paths, integrations) + ["ps"]
    r = run(cmd, timeout=DEFAULT_CMD_TIMEOUT)
    if r.ok and r.stdout:
        print("\n" + r.stdout)


def stack_has_running_containers(
    install_paths: InstallPaths, integrations: List[str]
) -> bool:
    cmd = compose_runtime_cmd(install_paths, integrations) + [
        "ps",
        "--status",
        "running",
        "-q",
    ]
    r = run(cmd, timeout=DEFAULT_CMD_TIMEOUT)
    return r.ok and bool(r.stdout.strip())


def bring_down_stack_if_possible(
    install_paths: InstallPaths, integrations: Optional[List[str]] = None
) -> None:
    if not install_paths.images_compose.exists() or not install_paths.runtime_compose.exists():
        info("Compose files not found; skipping Docker Compose shutdown")
        return

    info("Bringing down Docker Compose stack...")

    cmd = compose_runtime_cmd(install_paths, integrations or []) + ["down"]

    r = run(cmd, timeout=LONG_CMD_TIMEOUT)
    if not r.ok:
        info(
            "Could not stop stack with Docker Compose. "
            f"Continuing uninstall anyway.\nDetails:\n{r.stderr or r.stdout}"
        )
    else:
        ok("Stack stopped.")


def validate_compose_files(
    install_paths: InstallPaths, integrations: Optional[List[str]] = None
) -> None:
    integrations = integrations or []
    cmd = compose_runtime_cmd(install_paths, integrations) + ["config", "--format", "json"]
    r = run(cmd, timeout=DEFAULT_CMD_TIMEOUT)
    if not r.ok:
        die(
            f"Compose configuration validation failed:\nCommand: {' '.join(cmd)}\n\n"
            f"{r.stderr or r.stdout}"
        )
    ok("Compose files validated")


def get_rendered_compose_config(
    install_paths: InstallPaths, integrations: Optional[List[str]] = None
) -> Dict:
    integrations = integrations or []
    cmd = compose_runtime_cmd(install_paths, integrations) + ["config", "--format", "json"]
    r = run(cmd, timeout=DEFAULT_CMD_TIMEOUT)
    if not r.ok:
        die(
            f"Failed to render Compose configuration:\nCommand: {' '.join(cmd)}\n\n"
            f"{r.stderr or r.stdout}"
        )

    try:
        data = json.loads(r.stdout)
    except Exception as e:
        die(f"Failed to parse rendered Compose JSON:\n{e}")

    if not isinstance(data, dict):
        die("Rendered Compose configuration is invalid: expected a JSON object")

    return data


def compute_required_images(rendered: Dict) -> List[str]:
    """
    Computes required images from the rendered Compose configuration so that
    profiles, merges, and interpolation are resolved by Docker Compose.
    """
    services = rendered.get("services", {})
    if not isinstance(services, dict):
        die("Rendered Compose configuration is invalid: missing 'services' mapping")

    images = set()
    for svc in services.values():
        if not isinstance(svc, dict):
            continue
        image = svc.get("image")
        if isinstance(image, str) and image.strip():
            images.add(image.strip())

    return sorted(images)


def compute_named_volumes(rendered: Dict) -> List[str]:
    """Return Docker volume names from rendered Compose configuration."""
    volumes = rendered.get("volumes", {})
    if not isinstance(volumes, dict):
        die("Rendered Compose configuration is invalid: 'volumes' must be a mapping")

    names = set()
    for volume_key, spec in volumes.items():
        if isinstance(spec, dict):
            name = spec.get("name")
            if isinstance(name, str) and name.strip():
                names.add(name.strip())
                continue
        if isinstance(volume_key, str) and volume_key.strip():
            names.add(volume_key.strip())

    return sorted(names)


def verify_required_bind_mounts(rendered) -> List[Tuple[Path, str, bool]]:
    """Validate host paths used by rendered Compose bind mounts before startup."""
    info("Checking host bind mount paths from rendered Compose configuration...")

    mounts = list(_iter_bind_mounts(rendered))
    missing = []
    unreadable = []
    unwritable = []
    container_unwritable = []

    for source, target, read_only in mounts:
        if not source.exists():
            missing.append((source, target))
            continue
        if not source.is_file() and not source.is_dir():
            unreadable.append((source, target, "not a regular file or directory"))
            continue
        if not _path_accessible(source, read=True):
            unreadable.append((source, target, "not readable"))
        if not read_only:
            if not _path_accessible(source, write=True):
                unwritable.append((source, target))
            if not _path_writable_by_uid_gid(
                source,
                CONTAINER_WRITABLE_UID,
                CONTAINER_WRITABLE_GID,
            ):
                container_unwritable.append((source, target))

    if missing or unreadable or unwritable or container_unwritable:
        lines = ["Host bind mount preflight failed:"]
        if missing:
            lines.append("Missing bind mount source path(s):")
            lines.extend(f"  - {source} -> {target}" for source, target in missing)
        if unreadable:
            lines.append("Unreadable bind mount source path(s):")
            lines.extend(
                f"  - {source} -> {target} ({reason})"
                for source, target, reason in unreadable
            )
        if unwritable:
            lines.append("Unwritable read/write bind mount source path(s):")
            lines.extend(f"  - {source} -> {target}" for source, target in unwritable)
        if container_unwritable:
            lines.append(
                "Read/write bind mount source path(s) may not be writable by "
                f"container UID/GID {CONTAINER_WRITABLE_UID}:{CONTAINER_WRITABLE_GID}:"
            )
            lines.extend(f"  - {source} -> {target}" for source, target in container_unwritable)
        lines.append("Create the path or fix ownership/permissions before starting Parseus.")
        die("\n".join(lines))

    ok(f"Host bind mount check passed ({len(mounts)} bind mount(s) checked)")
    return mounts


def _iter_bind_mounts(rendered) -> List[Tuple[Path, str, bool]]:
    services = rendered.get("services", {})
    if not isinstance(services, dict):
        die("Rendered Compose configuration is invalid: missing 'services' mapping")

    mounts: List[Tuple[Path, str, bool]] = []
    for svc in services.values():
        if not isinstance(svc, dict):
            continue
        volumes = svc.get("volumes", [])
        if not isinstance(volumes, list):
            continue
        for entry in volumes:
            mount = _normalize_bind_mount_entry(entry)
            if mount is not None:
                mounts.append(mount)
    return mounts


def _normalize_bind_mount_entry(entry) -> Optional[Tuple[Path, str, bool]]:
    if isinstance(entry, dict):
        if entry.get("type") != "bind":
            return None
        source = entry.get("source")
        target = entry.get("target") or ""
        if not isinstance(source, str) or not source.strip():
            return None
        read_only = bool(entry.get("read_only") or entry.get("readonly"))
        return (Path(source), str(target), read_only)

    if isinstance(entry, str):
        parts = entry.split(":")
        if len(parts) < 2:
            return None
        source = parts[0]
        if not source.startswith(("/", "./", "../", "~")):
            return None
        target = parts[1]
        options = parts[2:]
        read_only = "ro" in {option.split(",", 1)[0] for option in options}
        return (Path(source).expanduser(), target, read_only)

    return None


def _path_accessible(path: Path, *, read: bool = False, write: bool = False) -> bool:
    mode = 0
    if read:
        mode |= os.R_OK
    if write:
        mode |= os.W_OK
    return os.access(path, mode)


def _path_writable_by_uid_gid(path: Path, uid: int, gid: int) -> bool:
    try:
        stat_result = path.stat()
    except OSError:
        return False

    mode = stat_result.st_mode
    if stat_result.st_uid == uid and mode & 0o200:
        return True
    if stat_result.st_gid == gid and mode & 0o020:
        return True
    if mode & 0o002:
        return True
    return False


def verify_required_ports(rendered) -> List[Tuple[str, int]]:
    """
    Checks host ports from the rendered Compose configuration, including profiles.
    """
    info("Checking host ports from rendered Compose configuration...")

    services = rendered.get("services", {})
    if not isinstance(services, dict):
        die("Rendered Compose configuration is invalid: missing 'services' mapping")

    binds: List[Tuple[str, int]] = []
    for svc in services.values():
        if not isinstance(svc, dict):
            continue
        ports = svc.get("ports", [])
        if not isinstance(ports, list):
            continue
        for entry in ports:
            binds.extend(_normalize_compose_port_entry(entry))

    uniq = []
    seen = set()
    for host, port in binds:
        if (host, port) not in seen:
            seen.add((host, port))
            uniq.append((host, port))

    in_use = []
    for host, port in uniq:
        hosts_to_check = [host]

        if host == "0.0.0.0":
            hosts_to_check.extend(["127.0.0.1", "localhost"])
        elif host == "::":
            hosts_to_check.extend(["::1", "localhost"])

        checked = set()
        for h in hosts_to_check:
            if h in checked:
                continue
            checked.add(h)
            if not port_is_available(h, port):
                in_use.append((host, port))
                break

    if in_use:
        msg = (
            "The following host ports required by the rendered Compose "
            "configuration appear to be in use:\n"
        )
        msg += "\n".join([f"  - {host}:{port}" for host, port in in_use])
        msg += "\n\nStop the service(s) using these ports or change the Compose port mappings."
        die(msg)

    ok(f"Host port check passed ({len(uniq)} published port(s) checked)")
    return uniq


def _normalize_compose_port_entry(port_entry) -> List[Tuple[str, int]]:
    """
    Accepts Compose port entries from rendered JSON and returns a list of
    (host_ip, host_port) tuples.

    Handles:
      - short syntax strings like "127.0.0.1:443:443"
      - bracketed IPv6 strings like "[::1]:443:443"
      - dict syntax like {"published":"443","target":443,"host_ip":"127.0.0.1"}
      - port ranges like "8000-8005:80-85" or published="8000-8005"
    """
    binds: List[Tuple[str, int]] = []

    if isinstance(port_entry, str):
        item = _strip_quotes(port_entry)
        item = item.split("/", 1)[0].strip()

        host_ip = "0.0.0.0"
        host_port = None

        if item.startswith("["):
            end = item.find("]")
            if end == -1:
                return []
            host_ip = item[1:end].strip()
            rest = item[end + 1 :]
            if not rest.startswith(":"):
                return []
            rest = rest[1:]
            parts = rest.split(":")
            if len(parts) < 2:
                return []
            host_port = parts[0].strip()
        else:
            parts = item.split(":")
            if len(parts) == 1:
                return []
            if len(parts) == 2:
                host_port = parts[0].strip()
            else:
                host_ip = parts[0].strip()
                host_port = parts[1].strip()

    elif isinstance(port_entry, dict):
        published = port_entry.get("published")
        if published in (None, ""):
            return []
        host_ip = str(port_entry.get("host_ip") or "0.0.0.0").strip()
        host_port = str(published).strip()
    else:
        return []

    if not host_port:
        return []

    if "-" in host_port:
        first, last = host_port.split("-", 1)
        try:
            for host_port_value in range(int(first), int(last) + 1):
                binds.append((host_ip, host_port_value))
        except ValueError:
            return []
    else:
        try:
            binds.append((host_ip, int(host_port)))
        except ValueError:
            return []

    return binds


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value
