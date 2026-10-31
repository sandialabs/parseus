from __future__ import annotations

from dataclasses import dataclass

from manage_parseus_lib.config.model import InstallerConfig
from manage_parseus_lib.install.paths import InstallPaths


@dataclass(frozen=True)
class DeploymentContext:
    """Runtime context shared by Parseus deployment commands."""

    config: InstallerConfig
    paths: InstallPaths
