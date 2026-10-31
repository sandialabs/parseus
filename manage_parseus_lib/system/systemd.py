from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Optional

from manage_parseus_lib.constants import INTEGRATION_TO_COMPOSE_PROFILE
from manage_parseus_lib.file_ops import atomic_write_text, backup_file_before_overwrite
from manage_parseus_lib.install.paths import InstallPaths
from manage_parseus_lib.output import die, info, ok, warn
from manage_parseus_lib.process import CmdResult, run

SYSTEMD_UNIT_NAME = "parseus.service"
SYSTEMD_UNIT_PATH = Path("/etc/systemd/system/parseus.service")
SYSTEMD_ENV_FILENAME = "parseus.env"

# systemctl calls are quick, but daemon-reload / enable can briefly block on a
# busy manager, so allow a small timeout window.
_SYSTEMCTL_TIMEOUT = 60


def systemd_available() -> bool:
    """Return True only when systemctl exists on PATH.

    This is the single guard that preserves the offline / minimal-host promise:
    on a host without systemd, the installer and runtime commands fall back to
    driving Docker Compose directly, exactly as before.
    """
    return shutil.which("systemctl") is not None


def _systemd_env_path(install_paths: InstallPaths) -> Path:
    return install_paths.runtime_root / SYSTEMD_ENV_FILENAME


def _compose_profiles_value(integrations: List[str]) -> str:
    profiles: List[str] = []
    seen = set()
    for integration in integrations:
        profile = INTEGRATION_TO_COMPOSE_PROFILE.get(integration)
        if profile and profile not in seen:
            seen.add(profile)
            profiles.append(profile)
    return ",".join(profiles)


def _render_env_file(integrations: List[str]) -> str:
    # Native Compose env var; equivalent to the --profile flags used by
    # compose_runtime_cmd(), but expressible in a static unit's EnvironmentFile.
    return (
        "# Managed by manage-parseus. Regenerated on install/upgrade and on\n"
        "# runtime integration changes. Edit through manage-parseus, not by hand.\n"
        f"COMPOSE_PROFILES={_compose_profiles_value(integrations)}\n"
    )


def _render_unit(install_paths: InstallPaths) -> str:
    docker = shutil.which("docker") or "/usr/bin/docker"
    env_file = _systemd_env_path(install_paths)
    # These -f / --env-file / --project-name values mirror compose_runtime_cmd()
    # exactly, so the unit runs the same stack the script would.
    compose = (
        f"{docker} compose --project-name {install_paths.project_name} "
        f"--env-file {install_paths.compose_env_file} "
        f"-f {install_paths.images_compose} "
        f"-f {install_paths.runtime_compose}"
    )
    return (
        "[Unit]\n"
        "Description=Parseus Docker Compose stack\n"
        "Requires=docker.service\n"
        "After=docker.service network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        "RemainAfterExit=yes\n"
        f"EnvironmentFile={env_file}\n"
        f"ExecStart=/bin/sh -c '{compose} up --no-build -d'\n"
        f"ExecStop=/bin/sh -c '{compose} down'\n"
        f"ExecReload=/bin/sh -c '{compose} up --no-build -d'\n"
        "TimeoutStartSec=0\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def write_systemd_integration_env(
    install_paths: InstallPaths, integrations: List[str]
) -> None:
    """Refresh only the COMPOSE_PROFILES env file (cheap runtime update).

    The file is skipped when its content is already current, so non-root
    ``parseus-admin`` members can run ``up``/``restart`` without write access
    to the runtime directory.
    """
    if not systemd_available():
        return
    env_path = _systemd_env_path(install_paths)
    data = _render_env_file(integrations)
    try:
        if env_path.is_file() and env_path.read_text(encoding="utf-8") == data:
            return
    except OSError:
        pass  # Unreadable: fall through and attempt the write.
    try:
        backup_file_before_overwrite(env_path, data, mode=0o644, label="systemd env file")
        atomic_write_text(env_path, data, mode=0o644)
    except PermissionError as e:
        die(
            f"Cannot write {env_path}: {e.strerror or e}.\n"
            "Changing the selected integrations requires root privileges.\n"
            "Re-run with: sudo manage-parseus <command>"
        )


def install_systemd_unit(install_paths: InstallPaths, integrations: List[str]) -> None:
    """Write and enable the parseus systemd unit; no-op without systemd."""
    if not systemd_available():
        info("systemctl not found; skipping systemd unit installation")
        return

    write_systemd_integration_env(install_paths, integrations)

    unit_text = _render_unit(install_paths)
    backup_file_before_overwrite(
        SYSTEMD_UNIT_PATH, unit_text, mode=0o644, label="systemd unit"
    )
    atomic_write_text(SYSTEMD_UNIT_PATH, unit_text, mode=0o644)

    _systemctl(["daemon-reload"])
    r = _systemctl(["enable", SYSTEMD_UNIT_NAME])
    if r.ok:
        ok(f"Installed and enabled systemd unit: {SYSTEMD_UNIT_PATH}")
    else:
        warn(
            "Wrote systemd unit but could not enable it "
            f"({r.stderr or r.stdout}). Enable it manually with: "
            f"systemctl enable {SYSTEMD_UNIT_NAME}"
        )


def remove_systemd_unit() -> None:
    """Disable, stop, and remove the parseus systemd unit; no-op without systemd."""
    if not systemd_available():
        return
    if SYSTEMD_UNIT_PATH.exists():
        _systemctl(["disable", "--now", SYSTEMD_UNIT_NAME])
        try:
            SYSTEMD_UNIT_PATH.unlink()
            info(f"Removed systemd unit: {SYSTEMD_UNIT_PATH}")
        except OSError as e:
            warn(f"Could not remove systemd unit {SYSTEMD_UNIT_PATH}: {e}")
        _systemctl(["daemon-reload"])


def unit_is_active() -> bool:
    """Return True when the parseus unit is currently active."""
    r = _systemctl(["is-active", SYSTEMD_UNIT_NAME])
    return r.stdout.strip() == "active"


def start_via_systemd() -> bool:
    """Bring the stack to the desired state through systemd.

    Returns False when systemd is unavailable or the action failed, so callers
    fall back to driving Docker Compose directly.

    The unit is Type=oneshot with RemainAfterExit=yes, so once it has run it
    stays "active" and ``systemctl start`` is a no-op. That would silently
    ignore changes such as a new COMPOSE_PROFILES value. When the unit is
    already active, run ExecReload instead, which re-reads the EnvironmentFile
    and re-runs ``compose up --no-build -d`` to reconcile the stack.
    """
    if not systemd_available():
        return False
    if unit_is_active():
        action = "reload"
        r = _systemctl(["reload", SYSTEMD_UNIT_NAME])
    else:
        action = "start"
        r = _systemctl(["start", SYSTEMD_UNIT_NAME])
    if not r.ok:
        warn(f"systemctl {action} failed: {r.stderr or r.stdout}")
    return r.ok


def stop_via_systemd() -> bool:
    """Stop the stack through systemd. Returns False when systemd is unavailable."""
    if not systemd_available():
        return False
    r = _systemctl(["stop", SYSTEMD_UNIT_NAME])
    if not r.ok:
        warn(f"systemctl stop failed: {r.stderr or r.stdout}")
    return r.ok


def systemd_status_facts() -> Optional[dict]:
    """Return {'enabled': ..., 'active': ...} or None when systemd is absent."""
    if not systemd_available():
        return None
    enabled = _systemctl(["is-enabled", SYSTEMD_UNIT_NAME])
    active = _systemctl(["is-active", SYSTEMD_UNIT_NAME])
    # is-enabled / is-active return non-zero for disabled/inactive but still
    # print the state word on stdout, so prefer stdout and fall back to rc.
    return {
        "enabled": enabled.stdout.strip() or (enabled.stderr.strip() or "unknown"),
        "active": active.stdout.strip() or (active.stderr.strip() or "unknown"),
    }


def _systemctl(args: List[str]) -> CmdResult:
    return run(["systemctl", *args], timeout=_SYSTEMCTL_TIMEOUT)
