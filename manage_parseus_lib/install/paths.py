from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path
from manage_parseus_lib.constants import DEFAULT_DOCKER_PROJECT_NAME
from manage_parseus_lib.output import die

SYSTEM_APP_ROOT = Path("/opt/parseus")
SYSTEM_CONFIG_ROOT = Path("/etc/parseus")
SYSTEM_DATA_ROOT = Path("/var/lib/parseus")
SYSTEM_STATE_ROOT = SYSTEM_DATA_ROOT / "state"
SYSTEM_RUNTIME_ROOT = SYSTEM_DATA_ROOT / "runtime"
SYSTEM_DROP_DIR = Path("/srv/parseus/ftp")
SYSTEM_LOG_ROOT = Path("/var/log/parseus")
SYSTEM_WRAPPER_PATH = Path("/usr/local/bin/manage-parseus")


@dataclass(frozen=True)
class InstallPaths:
    """Resolved filesystem layout for the system-wide Parseus deployment."""

    source_root: Path
    app_root: Path = SYSTEM_APP_ROOT
    config_root: Path = SYSTEM_CONFIG_ROOT
    data_root: Path = SYSTEM_DATA_ROOT
    state_root: Path = SYSTEM_STATE_ROOT
    runtime_root: Path = SYSTEM_RUNTIME_ROOT
    drop_dir: Path = SYSTEM_DROP_DIR
    log_root: Path = SYSTEM_LOG_ROOT
    wrapper_path: Path = SYSTEM_WRAPPER_PATH
    project_name: str = DEFAULT_DOCKER_PROJECT_NAME

    @property
    def certs_dir(self) -> Path:
        return self.config_root / "certs"

    @property
    def env_dir(self) -> Path:
        return self.config_root / "envs"

    @property
    def images_dir(self) -> Path:
        return self.source_root / "images"

    @property
    def build_compose(self) -> Path:
        return self.source_root / "compose.build.yaml"

    @property
    def runtime_compose(self) -> Path:
        return self.runtime_root / "compose.runtime.yaml"

    @property
    def images_compose(self) -> Path:
        return self.runtime_root / "compose.images.yaml"

    @property
    def compose_env_file(self) -> Path:
        return self.config_root / "compose.env"

    @property
    def state_dir(self) -> Path:
        return self.state_root

    @property
    def current_manifest(self) -> Path:
        return self.state_dir / "current_manifest.json"

    @property
    def history_dir(self) -> Path:
        return self.state_dir / "history"

    @property
    def winlog_logstash_state_dir(self) -> Path:
        return self.data_root / "winlog" / "logstash"


def build_paths(
    source_root: Path | None = None,
    project_name: str = DEFAULT_DOCKER_PROJECT_NAME,
) -> InstallPaths:
    return InstallPaths(
        source_root=(source_root or script_dir()).resolve(),
        app_root=SYSTEM_APP_ROOT.resolve(),
        config_root=SYSTEM_CONFIG_ROOT.resolve(),
        data_root=SYSTEM_DATA_ROOT.resolve(),
        state_root=SYSTEM_STATE_ROOT.resolve(),
        runtime_root=SYSTEM_RUNTIME_ROOT.resolve(),
        drop_dir=SYSTEM_DROP_DIR.resolve(),
        log_root=SYSTEM_LOG_ROOT.resolve(),
        # Do NOT resolve(): the wrapper is a symlink we own. Resolving it here
        # would follow the link to the installed script, so uninstall's
        # is_symlink() check fails and the wrapper is wrongly left in place.
        wrapper_path=SYSTEM_WRAPPER_PATH,
        project_name=project_name,
    )


def with_project_name(install_paths: InstallPaths, project_name: str) -> InstallPaths:
    return InstallPaths(
        source_root=install_paths.source_root,
        app_root=install_paths.app_root,
        config_root=install_paths.config_root,
        data_root=install_paths.data_root,
        state_root=install_paths.state_root,
        runtime_root=install_paths.runtime_root,
        drop_dir=install_paths.drop_dir,
        log_root=install_paths.log_root,
        wrapper_path=install_paths.wrapper_path,
        project_name=project_name,
    )


def script_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def has_runtime_install_markers(install_paths: InstallPaths) -> bool:
    """Return True when the fixed system install layout has usable runtime markers."""
    required = [
        install_paths.app_root,
        install_paths.config_root,
        install_paths.runtime_compose,
        install_paths.images_compose,
    ]
    return all(p.exists() for p in required)


def has_complete_install_state(install_paths: InstallPaths) -> bool:
    """Return True when runtime markers and the installer manifest are present."""
    return has_runtime_install_markers(install_paths) and install_paths.current_manifest.exists()


def is_installed(install_paths: InstallPaths) -> bool:
    return has_runtime_install_markers(install_paths)

def require_not_installed(install_paths: InstallPaths) -> None:
    if is_installed(install_paths):
        die(
            "Parseus appears to already be installed.\n"
            "Use `upgrade` to update the installation, or `uninstall` first."
        )

def require_installed(install_paths: InstallPaths) -> None:
    if not is_installed(install_paths):
        die("Parseus does not appear to be installed.\n" "Use `install` first.")

def source_is_install_root(install_paths: InstallPaths) -> bool:
    """Return True when the bundle source directory is, or lies inside, the app root.

    This happens when ``manage-parseus`` is run through the installed symlink:
    the script resolves to ``<app_root>/manage_parseus.py``, so the "source"
    and "destination" for file refresh are the same directory. A source nested
    inside the app root is rejected too, because refreshing the app root would
    delete or overwrite the very files being copied.
    """
    source = install_paths.source_root.resolve()
    app_root = install_paths.app_root.resolve()
    try:
        # Same device/inode catches bind mounts and case-insensitive filesystems.
        if source.samefile(app_root):
            return True
    except OSError:
        pass  # A missing path cannot be the same directory; fall through.
    # Path.is_relative_to() requires Python 3.9; the installer supports 3.8.
    try:
        source.relative_to(app_root)
    except ValueError:
        return False
    return True


def require_source_outside_install_root(install_paths: InstallPaths, command: str) -> None:
    if source_is_install_root(install_paths):
        die(
            f"Refusing to {command} from the installed copy of manage-parseus "
            f"({install_paths.app_root}).\n"
            "Run it from an unpacked Parseus release bundle or repository checkout instead:\n"
            f"  cd /path/to/new-parseus-release && sudo python3 manage_parseus.py {command}"
        )


def validate_system_managed_path(path: Path) -> None:
    resolved = path.resolve()
    forbidden_unix = {
        Path("/"),
        Path("/opt"),
        Path("/usr"),
        Path("/etc"),
        Path("/var"),
        Path.home(),
    }
    if resolved in forbidden_unix:
        die(
            f"Refusing to use unsafe install root: {resolved}\nChoose a dedicated subdirectory instead."
        )

    if resolved.parent == resolved:
        die(
            f"Refusing to use unsafe install root: {resolved}\nChoose a dedicated subdirectory instead."
        )

def require_linux() -> None:
    if platform.system() != "Linux":
        die("This installer is supported only on Linux.")

