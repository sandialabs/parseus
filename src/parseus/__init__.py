from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _package_version

try:
    __version__ = _package_version("parseus")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
