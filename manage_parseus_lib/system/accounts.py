from __future__ import annotations

import grp
import pwd
import shutil
from dataclasses import dataclass
from typing import Optional

from manage_parseus_lib.constants import DEFAULT_CMD_TIMEOUT
from manage_parseus_lib.install.paths import SYSTEM_DATA_ROOT
from manage_parseus_lib.output import die, ok
from manage_parseus_lib.process import run
from manage_parseus_lib.types import InstallManifest, ManifestSystemAccounts

SERVICE_USER = "parseus"
SERVICE_GROUP = "parseus"
ADMIN_GROUP = "parseus-admin"
SERVICE_HOME = SYSTEM_DATA_ROOT
SERVICE_SHELL = "/usr/sbin/nologin"
ALLOWED_SERVICE_SHELLS = {SERVICE_SHELL, "/sbin/nologin", "/bin/false"}


@dataclass(frozen=True)
class SystemAccountProvisioning:
    service_user: str = SERVICE_USER
    service_group: str = SERVICE_GROUP
    admin_group: str = ADMIN_GROUP
    created_service_user: bool = False
    created_service_group: bool = False
    created_admin_group: bool = False

    def as_manifest_data(self) -> ManifestSystemAccounts:
        return {
            "service_user": self.service_user,
            "service_group": self.service_group,
            "admin_group": self.admin_group,
            "created_service_user": self.created_service_user,
            "created_service_group": self.created_service_group,
            "created_admin_group": self.created_admin_group,
        }


def ensure_system_accounts() -> SystemAccountProvisioning:
    """Create or validate Parseus system user/groups for system-wide installs."""
    created_service_group = ensure_group(SERVICE_GROUP)
    created_admin_group = ensure_group(ADMIN_GROUP)
    created_service_user = ensure_service_user(SERVICE_USER, SERVICE_GROUP)

    return SystemAccountProvisioning(
        created_service_user=created_service_user,
        created_service_group=created_service_group,
        created_admin_group=created_admin_group,
    )


def ensure_group(name: str) -> bool:
    if group_exists(name):
        ok(f"System group exists: {name}")
        return False

    require_command("groupadd")
    result = run(["groupadd", "--system", name], timeout=DEFAULT_CMD_TIMEOUT)
    if not result.ok:
        die(f"Failed to create system group {name!r}:\n{result.stderr or result.stdout}")

    ok(f"Created system group: {name}")
    return True


def ensure_service_user(user: str, group: str) -> bool:
    if user_exists(user):
        validate_existing_service_user(user, group)
        ok(f"System user exists: {user}")
        return False

    require_command("useradd")
    result = run(
        [
            "useradd",
            "--system",
            "--gid",
            group,
            "--home-dir",
            str(SERVICE_HOME),
            "--shell",
            SERVICE_SHELL,
            "--comment",
            "Parseus service user",
            user,
        ],
        timeout=DEFAULT_CMD_TIMEOUT,
    )
    if not result.ok:
        die(f"Failed to create system user {user!r}:\n{result.stderr or result.stdout}")

    ok(f"Created system user: {user}")
    return True


def validate_existing_service_user(user: str, expected_group: str) -> None:
    try:
        entry = pwd.getpwnam(user)
    except KeyError:
        die(f"System user {user!r} does not exist")

    try:
        primary_group = grp.getgrgid(entry.pw_gid).gr_name
    except KeyError:
        die(
            f"System user {user!r} has unknown primary group id {entry.pw_gid}. "
            f"Expected primary group {expected_group!r}."
        )

    if primary_group != expected_group:
        die(
            f"Existing user {user!r} has primary group {primary_group!r}; "
            f"expected {expected_group!r}. Refusing to reuse it."
        )

    if entry.pw_dir != str(SERVICE_HOME):
        die(
            f"Existing user {user!r} has home directory {entry.pw_dir!r}; "
            f"expected {str(SERVICE_HOME)!r}. Refusing to reuse it."
        )

    if entry.pw_shell not in ALLOWED_SERVICE_SHELLS:
        die(
            f"Existing user {user!r} has login shell {entry.pw_shell!r}; "
            "expected a non-login service shell. Refusing to reuse it."
        )


def remove_system_accounts(manifest: Optional[InstallManifest]) -> None:
    account_data = manifest.get("system_accounts") if manifest else None
    if not isinstance(account_data, dict):
        ok("No installer-created system account metadata found; leaving system accounts in place")
        return

    service_user = str(account_data.get("service_user") or SERVICE_USER)
    service_group = str(account_data.get("service_group") or SERVICE_GROUP)
    admin_group = str(account_data.get("admin_group") or ADMIN_GROUP)

    if account_data.get("created_service_user") is True:
        remove_system_user(service_user)
    if account_data.get("created_service_group") is True:
        remove_system_group(service_group)
    if account_data.get("created_admin_group") is True:
        remove_system_group(admin_group)


def remove_system_user(name: str) -> None:
    if not user_exists(name):
        ok(f"System user already absent: {name}")
        return
    require_command("userdel")
    result = run(["userdel", name], timeout=DEFAULT_CMD_TIMEOUT)
    if not result.ok:
        die(f"Failed to remove system user {name!r}:\n{result.stderr or result.stdout}")
    ok(f"Removed system user: {name}")


def remove_system_group(name: str) -> None:
    if not group_exists(name):
        ok(f"System group already absent: {name}")
        return
    require_command("groupdel")
    result = run(["groupdel", name], timeout=DEFAULT_CMD_TIMEOUT)
    if not result.ok:
        die(f"Failed to remove system group {name!r}:\n{result.stderr or result.stdout}")
    ok(f"Removed system group: {name}")


def group_exists(name: str) -> bool:
    try:
        grp.getgrnam(name)
        return True
    except KeyError:
        return False


def user_exists(name: str) -> bool:
    try:
        pwd.getpwnam(name)
        return True
    except KeyError:
        return False


def require_command(name: str) -> None:
    if shutil.which(name) is None:
        die(
            f"Required system account command not found in PATH: {name}\n"
            "Install standard Linux shadow/user management tools and retry."
        )
