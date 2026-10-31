from __future__ import annotations

import re

import parseus


def test_package_exposes_runtime_version() -> None:
    assert isinstance(parseus.__version__, str)
    assert parseus.__version__
    assert re.match(r"^\d+\.\d+\.\d+", parseus.__version__)


def test_package_version_falls_back_when_distribution_metadata_is_missing(monkeypatch) -> None:
    import importlib
    import importlib.metadata

    original_version = importlib.metadata.version

    def fake_version(distribution_name: str) -> str:
        if distribution_name == "parseus":
            raise importlib.metadata.PackageNotFoundError(distribution_name)
        return original_version(distribution_name)

    monkeypatch.setattr(importlib.metadata, "version", fake_version)

    reloaded = importlib.reload(parseus)

    assert reloaded.__version__ == "0.0.0+unknown"

    monkeypatch.undo()
    importlib.reload(parseus)
