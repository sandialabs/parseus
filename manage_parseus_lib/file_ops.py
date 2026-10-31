from __future__ import annotations

import os
import secrets
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from manage_parseus_lib.output import info, ok, warn

FileData = Union[str, bytes]


def set_restrictive_mode(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except Exception as e:
        info(f"Could not set permissions on {path}: {e}")


def ensure_directory(path: Path, mode: Optional[int] = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if mode is not None:
        set_restrictive_mode(path, mode)


def atomic_write_text(path: Path, data: str, mode: Optional[int] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", text=True
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        if mode is not None:
            set_restrictive_mode(tmp_path, mode)
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def atomic_write_bytes(path: Path, data: bytes, mode: Optional[int] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        if mode is not None:
            set_restrictive_mode(tmp_path, mode)
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def backup_file_before_overwrite(
    path: Path,
    new_data: FileData,
    *,
    mode: int = 0o600,
    label: Optional[str] = None,
) -> None:
    """Back up an existing file when its bytes differ from a new payload."""
    if not path.exists() or not path.is_file():
        return

    new_bytes = new_data.encode("utf-8") if isinstance(new_data, str) else new_data
    try:
        current_bytes = path.read_bytes()
    except OSError as e:
        warn(
            "Could not read existing file before rewrite; "
            f"skipping backup for {path}: {e}"
        )
        return

    if current_bytes == new_bytes:
        return

    backup_dir = path.parent / ".backups"
    ensure_directory(backup_dir, mode=0o700)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup_path = backup_dir / f"{path.name}-{ts}.bak"
    if backup_path.exists():
        suffix = secrets.token_hex(4)
        backup_path = backup_dir / f"{path.name}-{ts}-{suffix}.bak"

    shutil.copy2(path, backup_path)
    set_restrictive_mode(backup_path, mode)
    ok(f"Backed up previous {label or path.name} to {backup_path}")
