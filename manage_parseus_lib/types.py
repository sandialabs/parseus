from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional, TypedDict, Union

JsonScalar = Union[str, int, float, bool, None]
JsonValue = Union[JsonScalar, List["JsonValue"], Dict[str, "JsonValue"]]
JsonObject = Dict[str, JsonValue]

EnvValue = Union[str, int, bool]
EnvFileValue = Union[EnvValue, None]
EnvFileValues = Dict[str, str]
EnvFileWriteValues = Dict[str, EnvFileValue]
EnvDefaults = Dict[str, EnvValue]
EnvGenerators = Dict[str, Callable[[], str]]
EnvOverrides = Dict[str, Dict[str, str]]
ComposeEnv = Dict[str, str]
ImageIdMap = Dict[str, str]


class EnvFileSpec(TypedDict):
    header: str
    defaults: EnvDefaults
    generators: EnvGenerators


EnvFileSpecs = Dict[str, EnvFileSpec]


class InstallerConfigValues(TypedDict):
    config_file: Optional[Path]
    method: str
    integrations_arg: Optional[str]
    project_name: str
    public_url: str
    health_host: str
    https_port: int
    certificate_common_name: str
    certificate_days: int
    certificate_san_dns: List[str]
    certificate_san_ips: List[str]
    certificate_cert_file: Optional[Path]
    certificate_key_file: Optional[Path]
    env_overrides: EnvOverrides
    compose_env: ComposeEnv


class ManifestInstallerConfig(TypedDict, total=False):
    config_file: Optional[str]
    app_root: str
    config_root: str
    data_root: str
    log_root: str
    method: str
    project_name: str
    public_url: str
    health_host: str
    https_port: int
    certificate_common_name: str
    certificate_days: int
    certificate_san_dns: List[str]
    certificate_san_ips: List[str]
    certificate_source: str
    certificate_cert_file: Optional[str]
    certificate_key_file: Optional[str]
    compose_env_keys: List[str]
    compose_env_fingerprint: str
    known_compose_values: ComposeEnv
    env_override_files: List[str]
    env_override_keys: Dict[str, List[str]]
    env_overrides_fingerprint: str


class ManifestSystemAccounts(TypedDict):
    service_user: str
    service_group: str
    admin_group: str
    created_service_user: bool
    created_service_group: bool
    created_admin_group: bool


class InstallManifest(TypedDict, total=False):
    schema_version: int
    installed_at: str
    app_version: str
    integrations: List[str]
    all_images: List[str]
    app_owned_images: List[str]
    dependency_images: List[str]
    resolved_images: ImageIdMap
    named_volumes: List[str]
    installer_config: ManifestInstallerConfig
    system_accounts: ManifestSystemAccounts


ManifestData = InstallManifest
