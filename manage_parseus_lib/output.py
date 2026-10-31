from __future__ import annotations

import sys
from typing import NoReturn

from manage_parseus_lib.errors import ManageParseusError


def print_error(msg: str) -> None:
    print(f"[\033[31mERROR\033[0m] {msg}", file=sys.stderr)


def die(msg: str, rc: int = 1) -> NoReturn:
    """Raise a user-facing error without terminating the process immediately."""
    raise ManageParseusError(msg, rc=rc)


def warn(msg: str) -> None:
    print(f"[\033[33mWARN\033[0m] {msg}", file=sys.stderr)


def info(msg: str) -> None:
    print(f"[INFO] {msg}")


def ok(msg: str) -> None:
    print(f"[ \033[32mOK\033[0m ] {msg}")

