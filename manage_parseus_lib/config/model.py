from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from manage_parseus_lib.constants import (
    DEFAULT_DOCKER_PROJECT_NAME,
    DEFAULT_HOST,
    DEFAULT_HTTPS_PORT,
    DEFAULT_URL,
)
from manage_parseus_lib.types import ComposeEnv, EnvOverrides

@dataclass(frozen=True)
class InstallerConfig:
    """
    Effective installer configuration used by install, upgrade, and runtime commands.

    This object prevents deployment-specific settings from being spread across
    command handlers. Values are built from built-in defaults, optional config-file
    values, and explicit CLI overrides.
    """

    config_file: Optional[Path] = None
    method: str = "repository"
    integrations_arg: Optional[str] = None
    project_name: str = DEFAULT_DOCKER_PROJECT_NAME
    public_url: str = DEFAULT_URL
    health_host: str = DEFAULT_HOST
    https_port: int = DEFAULT_HTTPS_PORT
    certificate_common_name: str = "localhost"
    certificate_days: int = 825
    certificate_san_dns: List[str] = field(default_factory=lambda: ["localhost"])
    certificate_san_ips: List[str] = field(default_factory=lambda: ["127.0.0.1"])
    certificate_cert_file: Optional[Path] = None
    certificate_key_file: Optional[Path] = None
    env_overrides: EnvOverrides = field(default_factory=dict)
    compose_env: ComposeEnv = field(default_factory=dict)

