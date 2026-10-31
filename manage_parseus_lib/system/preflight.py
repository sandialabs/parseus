from __future__ import annotations

import grp
import os
import pwd
import shutil

from manage_parseus_lib.constants import DEFAULT_CMD_TIMEOUT
from manage_parseus_lib.output import die, info, ok
from manage_parseus_lib.process import run
from manage_parseus_lib.system.accounts import ADMIN_GROUP


def require_root_for_system_install(command: str) -> None:
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None or geteuid() != 0:
        die(
            "This Parseus management command requires root privileges.\n"
            f"Run: sudo manage-parseus {command}"
        )


def require_admin_privileges(command: str) -> None:
    """Allow root or members of the parseus-admin group to run a command.

    Runtime and status commands operate the already-installed stack and read
    installer-managed config/state. They do not need full root; membership in
    the ``parseus-admin`` group (which owns ``/etc/parseus`` and the state
    directory group) is sufficient. Root is always allowed.
    """
    geteuid = getattr(os, "geteuid", None)
    if geteuid is not None and geteuid() == 0:
        return

    # Check the *running process* credentials, not just /etc/group. A user who
    # was just added to the group with usermod is listed in /etc/group but their
    # existing sessions carry a stale supplementary-group set, so the kernel will
    # still deny file access. Gating on the effective credentials keeps the
    # privilege check aligned with what the filesystem will actually enforce.
    if process_in_group(ADMIN_GROUP):
        return

    if user_listed_in_group(ADMIN_GROUP):
        # In /etc/group but not in the current session's group set: the user has
        # been granted access but has not started a fresh session yet.
        die(
            f"You are a member of the {ADMIN_GROUP!r} group, but your current "
            "session does not have it active yet, so Parseus cannot read its "
            "state files.\n"
            "Start a new session for the group to take effect:\n"
            f"  newgrp {ADMIN_GROUP}      # activate the group in a subshell\n"
            "  # or log out and back in, or run with sudo:\n"
            f"Run: sudo manage-parseus {command}"
        )

    die(
        "This Parseus management command requires membership in the "
        f"{ADMIN_GROUP!r} group (or root).\n"
        f"Add your user with: sudo usermod -aG {ADMIN_GROUP} <user> "
        "(log out and back in), or run with sudo:\n"
        f"Run: sudo manage-parseus {command}"
    )


def process_in_group(group_name: str) -> bool:
    """Return True when the *running process* effectively belongs to the group.

    This reflects the credentials the kernel uses for file-permission checks
    (the effective/real gid and the supplementary group set), so it does not
    consider /etc/group membership that a not-yet-refreshed session lacks.
    """
    try:
        gid = grp.getgrnam(group_name).gr_gid
    except KeyError:
        return False

    getgroups = getattr(os, "getgroups", None)
    if getgroups is not None and gid in getgroups():
        return True

    getgid = getattr(os, "getgid", None)
    if getgid is not None and getgid() == gid:
        return True

    getegid = getattr(os, "getegid", None)
    if getegid is not None and getegid() == gid:
        return True

    return False


def user_listed_in_group(group_name: str) -> bool:
    """Return True when the user is listed in /etc/group for the group.

    Unlike :func:`process_in_group`, this reflects the on-disk group database
    and so is True even before a session has picked up a fresh group grant.
    """
    try:
        entry = grp.getgrnam(group_name)
    except KeyError:
        return False

    try:
        user = pwd.getpwuid(os.getuid()).pw_name
    except (KeyError, AttributeError):
        return False

    return user in entry.gr_mem or entry.gr_gid == getattr(os, "getgid", lambda: -1)()



def preflight(require_openssl: bool = False) -> None:
    parts = ["Docker", "Docker Compose v2"]
    if require_openssl:
        parts.insert(0, "OpenSSL")
    info(f"Preflight: checking {', '.join(parts)}...")

    if require_openssl:
        find_openssl()
    find_docker()
    find_compose()

def find_openssl() -> None:
    if shutil.which("openssl") is None:
        die(
            "OpenSSL not found in PATH. It is required to generate self-signed certificates.\n"
            "Install OpenSSL and ensure `openssl` is available."
        )
    ok("OpenSSL reachable")

def find_docker() -> None:
    if shutil.which("docker") is None:
        die(
            "Docker CLI not found in PATH.\n"
            "Install Docker Engine (or Docker Desktop) and ensure `docker` is available."
        )

    r = run(["docker", "--version"], timeout=DEFAULT_CMD_TIMEOUT)
    if not r.ok:
        die(
            f"Docker appears present but `docker --version` failed:\n{r.stderr or r.stdout}"
        )
    ok(r.stdout)

    r = run(["docker", "info"], timeout=DEFAULT_CMD_TIMEOUT)
    if not r.ok:
        details = (r.stderr or r.stdout or "").lower()
        permission_denied = (
            "permission denied" in details
            or "got permission denied" in details
            or "dial unix" in details
            or "connect: permission denied" in details
        )

        if permission_denied:
            die(
                "Docker daemon is running but your user cannot access it.\n"
                "This command needs Docker access in addition to Parseus "
                "management privileges.\n"
                "Resolve it in one of these ways:\n"
                " - run the command with sudo, for example:\n"
                "     sudo manage-parseus <command>\n"
                " - or ask an administrator to grant you Docker access "
                "(add your user to the `docker` group and re-login).\n"
                "Note: membership in the `docker` group grants "
                "root-equivalent access to the host.\n"
                f"Details:\n{r.stderr or r.stdout}"
            )

        die(
            "Docker daemon not reachable (`docker info` failed).\n"
            "Common causes:\n"
            " - Docker service not running\n"
            " - insufficient permissions to access Docker\n"
            "\nResolve it in one of these ways:\n"
            " - start the Docker service (for example: sudo systemctl start docker), or\n"
            " - run this command with sudo, or\n"
            " - ask an administrator to grant you Docker access "
            "(add your user to the `docker` group and re-login).\n"
            f"Details:\n{r.stderr or r.stdout}"
        )
    ok("Docker daemon reachable")

def find_compose() -> None:
    r = run(["docker", "compose", "version"], timeout=DEFAULT_CMD_TIMEOUT)
    if r.ok:
        ok(f"Compose available via `docker compose` ({r.stdout})")
        return

    die(
        "Docker Compose v2 not found.\n"
        "Expected Docker Compose as the `docker compose` CLI plugin.\n"
        "Install/enable Docker Compose v2 for your platform."
    )

