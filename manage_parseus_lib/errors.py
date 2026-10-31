from __future__ import annotations


class ManageParseusError(Exception):
    """Expected user-facing error from the Parseus deployment manager."""

    def __init__(self, message: str, rc: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.rc = rc
