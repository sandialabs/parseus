from __future__ import annotations

import argparse
import configparser
import ipaddress
import re
from pathlib import Path
from typing import List, Optional, cast

from manage_parseus_lib.config.model import InstallerConfig
from manage_parseus_lib.constants import (
    ARBITRARY_INSTALLER_CONFIG_SECTIONS,
    DEFAULT_DOCKER_PROJECT_NAME,
    DEFAULT_HOST,
    DEFAULT_HTTPS_PORT,
    DEFAULT_URL,
    ENV_CONFIG_SECTION_TO_FILE,
    INSTALLER_CONFIG_SECTION_OPTIONS,
    SUPPORTED_INSTALLER_CONFIG_SECTIONS,
)
from manage_parseus_lib.integrations import parse_integrations_value
from manage_parseus_lib.output import die, info
from manage_parseus_lib.system.health import build_default_public_url, default_health_host_for_bind
from manage_parseus_lib.types import ComposeEnv, EnvOverrides, InstallerConfigValues

def build_installer_config(args: argparse.Namespace) -> InstallerConfig:
    config_file = normalize_optional_path(getattr(args, "config", None))

    values: InstallerConfigValues = {
        "config_file": config_file,
        "method": "repository",
        "integrations_arg": None,
        "project_name": DEFAULT_DOCKER_PROJECT_NAME,
        "public_url": DEFAULT_URL,
        "health_host": DEFAULT_HOST,
        "https_port": DEFAULT_HTTPS_PORT,
        "certificate_common_name": "localhost",
        "certificate_days": 825,
        "certificate_san_dns": ["localhost"],
        "certificate_san_ips": ["127.0.0.1"],
        "certificate_cert_file": None,
        "certificate_key_file": None,
        "env_overrides": {},
        "compose_env": {},
    }

    if config_file is not None:
        parser = load_installer_config(config_file)
        merge_installer_config_file_values(values, parser, config_file)

    cli_method = getattr(args, "method", None)
    if cli_method is not None:
        values["method"] = cli_method

    cli_integrations = getattr(args, "integrations", None)
    if cli_integrations is not None:
        values["integrations_arg"] = cli_integrations

    cli_project_name = getattr(args, "project_name", None)
    if cli_project_name is not None:
        values["project_name"] = cli_project_name

    validate_installer_config_values(values)
    compose_env = dict(cast(ComposeEnv, values["compose_env"]))
    compose_env["PARSEUS_PROJECT_NAME"] = cast(str, values["project_name"])
    values["compose_env"] = compose_env

    return InstallerConfig(
        config_file=cast(Optional[Path], values["config_file"]),
        method=cast(str, values["method"]),
        integrations_arg=cast(Optional[str], values["integrations_arg"]),
        project_name=cast(str, values["project_name"]),
        public_url=cast(str, values["public_url"]),
        health_host=cast(str, values["health_host"]),
        https_port=cast(int, values["https_port"]),
        certificate_common_name=cast(str, values["certificate_common_name"]),
        certificate_days=cast(int, values["certificate_days"]),
        certificate_san_dns=cast(List[str], values["certificate_san_dns"]),
        certificate_san_ips=cast(List[str], values["certificate_san_ips"]),
        certificate_cert_file=cast(Optional[Path], values["certificate_cert_file"]),
        certificate_key_file=cast(Optional[Path], values["certificate_key_file"]),
        env_overrides=cast(EnvOverrides, values["env_overrides"]),
        compose_env=cast(ComposeEnv, values["compose_env"]),
    )

def normalize_optional_path(path: Optional[Path]) -> Optional[Path]:
    if path is None:
        return None
    return normalize_path(path)

def normalize_path(path: Path) -> Path:
    return Path(path).expanduser()

def load_installer_config(path: Path) -> configparser.ConfigParser:
    if not path.exists() or not path.is_file():
        die(f"Installer configuration file not found: {path}")

    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    try:
        with path.open("r", encoding="utf-8") as f:
            parser.read_file(f)
    except configparser.Error as e:
        die(f"Failed to parse installer configuration file {path}: {e}")
    except OSError as e:
        die(f"Failed to read installer configuration file {path}: {e}")

    validate_installer_config_parser(parser, path)

    info(f"Loaded installer configuration: {path}")
    return parser

def validate_installer_config_parser(
    parser: configparser.ConfigParser, path: Path
) -> None:
    if parser.defaults():
        options = ", ".join(sorted(parser.defaults()))
        die(
            f"Unsupported [DEFAULT] option(s) in installer configuration {path}: "
            f"{options}. Put options in an explicit supported section instead."
        )

    for section in parser.sections():
        if section not in SUPPORTED_INSTALLER_CONFIG_SECTIONS:
            valid_sections = ", ".join(
                f"[{name}]" for name in sorted(SUPPORTED_INSTALLER_CONFIG_SECTIONS)
            )
            die(
                f"Unsupported installer config section [{section}] in {path}. "
                f"Supported sections: {valid_sections}"
            )

        if section in ARBITRARY_INSTALLER_CONFIG_SECTIONS:
            continue

        supported_options = INSTALLER_CONFIG_SECTION_OPTIONS[section]
        unknown_options = sorted(set(parser.options(section)) - supported_options)
        if unknown_options:
            valid_options = ", ".join(sorted(supported_options))
            die(
                f"Unsupported option(s) in installer config section [{section}] "
                f"in {path}: {', '.join(unknown_options)}. "
                f"Supported options: {valid_options}"
            )

def merge_installer_config_file_values(
    values: InstallerConfigValues, parser: configparser.ConfigParser, path: Path
) -> None:
    if parser.has_option("install", "method"):
        values["method"] = parser.get("install", "method").strip().lower()
    if parser.has_option("install", "integrations"):
        values["integrations_arg"] = parser.get("install", "integrations")
    if parser.has_option("install", "project_name"):
        values["project_name"] = parser.get("install", "project_name").strip()

    apply_nginx_config_values(values, parser, path)

    if parser.has_option("network", "public_url"):
        values["public_url"] = parser.get("network", "public_url").strip()
    if parser.has_option("network", "health_host"):
        values["health_host"] = parser.get("network", "health_host").strip()
    if parser.has_option("network", "https_port"):
        values["https_port"] = parse_config_int(
            parser, "network", "https_port", path
        )

    if parser.has_option("certificates", "common_name"):
        values["certificate_common_name"] = parser.get(
            "certificates", "common_name"
        ).strip()
    if parser.has_option("certificates", "days"):
        values["certificate_days"] = parse_config_int(
            parser, "certificates", "days", path
        )
    if parser.has_option("certificates", "san_dns"):
        values["certificate_san_dns"] = parse_csv_list(
            parser.get("certificates", "san_dns")
        )
    if parser.has_option("certificates", "san_ips"):
        values["certificate_san_ips"] = parse_csv_list(
            parser.get("certificates", "san_ips")
        )
    if parser.has_option("certificates", "cert_file"):
        values["certificate_cert_file"] = normalize_path(
            Path(parser.get("certificates", "cert_file").strip())
        )
    if parser.has_option("certificates", "key_file"):
        values["certificate_key_file"] = normalize_path(
            Path(parser.get("certificates", "key_file").strip())
        )

    values["env_overrides"] = parse_env_overrides(parser, path)
    compose_env = dict(values.get("compose_env", {}))
    compose_env.update(parse_compose_env(parser, path))
    values["compose_env"] = compose_env
    apply_compose_nginx_network_defaults(values, parser, path)

def apply_compose_nginx_network_defaults(
    values: InstallerConfigValues, parser: configparser.ConfigParser, path: Path
) -> None:
    compose_env = values.get("compose_env", {})
    if not isinstance(compose_env, dict):
        return

    https_bind = str(compose_env.get("PARSEUS_HTTPS_BIND", "")).strip()
    https_port_raw = str(compose_env.get("PARSEUS_HTTPS_PORT", "")).strip()
    if not https_bind and not https_port_raw:
        return

    if https_port_raw:
        try:
            https_port = int(https_port_raw)
        except ValueError:
            die(
                "Invalid Compose HTTPS port from installer configuration "
                f"in {path}: {https_port_raw!r}"
            )
        if not (1 <= https_port <= 65535):
            die(
                "Invalid Compose HTTPS port from installer configuration "
                f"in {path}: {https_port}"
            )
    else:
        https_port = int(values["https_port"])

    health_host = default_health_host_for_bind(https_bind) if https_bind else str(
        values["health_host"]
    )

    if not parser.has_option("network", "health_host"):
        values["health_host"] = health_host
    if not parser.has_option("network", "https_port"):
        values["https_port"] = https_port
    if not parser.has_option("network", "public_url"):
        values["public_url"] = build_default_public_url(health_host, https_port)

def apply_nginx_config_values(
    values: InstallerConfigValues, parser: configparser.ConfigParser, path: Path
) -> None:
    if not parser.has_section("nginx") or not parser.options("nginx"):
        return

    http_bind = parse_config_str(
        parser, "nginx", "http_bind", path, default="127.0.0.1"
    )
    http_port = parse_config_port(
        parser, "nginx", "http_port", path, default=80
    )
    https_bind = parse_config_str(
        parser, "nginx", "https_bind", path, default="127.0.0.1"
    )
    https_port = parse_config_port(
        parser, "nginx", "https_port", path, default=443
    )

    compose_env = dict(values.get("compose_env", {}))
    compose_env.update(
        {
            "PARSEUS_HTTP_BIND": http_bind,
            "PARSEUS_HTTP_PORT": str(http_port),
            "PARSEUS_HTTPS_BIND": https_bind,
            "PARSEUS_HTTPS_PORT": str(https_port),
        }
    )
    values["compose_env"] = compose_env

    health_host = default_health_host_for_bind(https_bind)
    values["health_host"] = health_host
    values["https_port"] = https_port
    values["public_url"] = build_default_public_url(health_host, https_port)

def parse_csv_list(raw: str) -> List[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def validate_certificate_name(label: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        die(f"Invalid certificate {label}: must not be empty")
    if any(ord(char) < 32 or char == "\x7f" for char in value):
        die(f"Invalid certificate {label}: control characters are not allowed")


def validate_certificate_ip(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        die("Invalid certificate san_ips entry: must not be empty")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        die(f"Invalid certificate san_ips entry: {value!r}")


def parse_config_str(
    parser: configparser.ConfigParser,
    section: str,
    option: str,
    path: Path,
    default: Optional[str] = None,
) -> str:
    if not parser.has_option(section, option):
        if default is None:
            die(f"Missing required [{section}] {option} in {path}")
        return default

    value = parser.get(section, option).strip()
    if not value:
        die(f"Invalid empty value for [{section}] {option} in {path}")
    return value

def parse_config_port(
    parser: configparser.ConfigParser,
    section: str,
    option: str,
    path: Path,
    default: int,
) -> int:
    if not parser.has_option(section, option):
        return default

    value = parse_config_int(parser, section, option, path)
    if not (1 <= value <= 65535):
        die(f"Invalid port for [{section}] {option} in {path}: {value}")
    return value

def parse_compose_env(parser: configparser.ConfigParser, path: Path) -> ComposeEnv:
    if not parser.has_section("compose"):
        return {}

    compose_env: ComposeEnv = {}
    for key, value in parser.items("compose"):
        key = key.strip()
        if not key:
            continue
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            die(
                f"Invalid Compose environment variable name in {path}: {key!r}. "
                "Use letters, digits, and underscores; do not start with a digit."
            )
        compose_env[key] = value.strip()

    return compose_env

def parse_env_overrides(
    parser: configparser.ConfigParser, path: Path
) -> EnvOverrides:
    overrides: EnvOverrides = {}

    for section in parser.sections():
        if not section.startswith("env."):
            continue

        env_file = ENV_CONFIG_SECTION_TO_FILE.get(section)
        if env_file is None:
            valid_sections = ", ".join(sorted(ENV_CONFIG_SECTION_TO_FILE))
            die(
                f"Unsupported environment config section [{section}] in {path}. "
                f"Supported sections: {valid_sections}"
            )

        section_values = {
            key.strip(): value.strip()
            for key, value in parser.items(section)
            if key.strip()
        }
        if section_values:
            overrides[env_file] = section_values

    return overrides

def parse_config_int(
    parser: configparser.ConfigParser, section: str, option: str, path: Path
) -> int:
    raw = parser.get(section, option).strip()
    try:
        return int(raw)
    except ValueError:
        die(f"Invalid integer for [{section}] {option} in {path}: {raw!r}")

def validate_installer_config_values(values: InstallerConfigValues) -> None:
    method = values["method"]
    if method not in {"bundle", "repository"}:
        die(
            f"Invalid install method: {method!r}. "
            "Expected one of: bundle, repository."
        )

    project_name = values["project_name"]
    if not isinstance(project_name, str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9_-]{0,62}", project_name
    ):
        die(
            f"Invalid Docker Compose project name: {project_name!r}. "
            "Use 1-63 lowercase letters, digits, underscores, or hyphens, "
            "starting with a letter or digit."
        )

    integrations_arg = values.get("integrations_arg")
    if integrations_arg is not None:
        parse_integrations_value(
            str(integrations_arg), source="installer configuration"
        )

    https_port = values["https_port"]
    if not isinstance(https_port, int) or not (1 <= https_port <= 65535):
        die(f"Invalid HTTPS port: {https_port!r}. Must be between 1 and 65535.")

    certificate_days = values["certificate_days"]
    if not isinstance(certificate_days, int) or certificate_days <= 0:
        die(f"Invalid certificate lifetime: {certificate_days!r}. Must be > 0.")

    validate_certificate_name("common_name", values["certificate_common_name"])
    san_dns = values["certificate_san_dns"]
    san_ips = values["certificate_san_ips"]
    if not isinstance(san_dns, list) or not isinstance(san_ips, list):
        die("Invalid certificate SAN configuration: expected comma-separated values")
    if not san_dns and not san_ips:
        die("Invalid certificate SAN configuration: at least one san_dns or san_ips value is required")
    for dns_name in san_dns:
        validate_certificate_name("san_dns", dns_name)
    for ip_value in san_ips:
        validate_certificate_ip(ip_value)

    cert_file = values.get("certificate_cert_file")
    key_file = values.get("certificate_key_file")
    if (cert_file is None) != (key_file is None):
        die(
            "Invalid certificate configuration: [certificates] cert_file and "
            "key_file must be provided together."
        )
    for label, cert_path in (("cert_file", cert_file), ("key_file", key_file)):
        if cert_path is None:
            continue
        if not isinstance(cert_path, Path) or not str(cert_path).strip():
            die(f"Invalid certificate {label}: must be a non-empty path")
        if not cert_path.exists() or not cert_path.is_file():
            die(f"Certificate {label} does not exist or is not a file: {cert_path}")
        try:
            with cert_path.open("rb") as f:
                f.read(1)
        except OSError as e:
            die(f"Certificate {label} is not readable: {cert_path}\nDetails: {e}")

    for key in ("public_url", "health_host", "certificate_common_name"):
        value = values[key]
        if not isinstance(value, str) or not value.strip():
            die(f"Invalid installer configuration value for {key}: must not be empty")

def apply_installer_config_to_args(
    args: argparse.Namespace, config: InstallerConfig
) -> None:
    cli_integrations = getattr(args, "integrations", None)

    args.project_name = config.project_name
    args.integrations = config.integrations_arg
    args.integrations_source = (
        "--integrations"
        if cli_integrations is not None
        else "installer configuration"
        if config.integrations_arg is not None
        else "--integrations"
    )
    if hasattr(args, "method"):
        args.method = config.method

