from __future__ import annotations

import argparse

from manage_parseus_lib.config.model import InstallerConfig
from manage_parseus_lib.config.sample import get_sample_config_text
from manage_parseus_lib.install.certificates import uses_external_tls_certificates
from manage_parseus_lib.formatting import format_list
from manage_parseus_lib.integrations import parse_integrations_value
from manage_parseus_lib.output import ok

def do_sample_config(args: argparse.Namespace) -> None:
    print(get_sample_config_text(), end="")

def do_validate_config(args: argparse.Namespace) -> None:
    config = args.installer_config
    print_effective_installer_config(config)
    ok("Installer configuration is valid")

def print_effective_installer_config(config: InstallerConfig) -> None:
    integrations = parse_integrations_value(
        config.integrations_arg, source="installer configuration"
    )
    integrations = integrations or []

    print("\nEffective Parseus installer configuration")
    print("=========================================")
    print(f"Config file: {config.config_file or 'none'}")
    print("Application root: /opt/parseus")
    print("Configuration root: /etc/parseus")
    print("State root: /var/lib/parseus")
    print("Log root: /var/log/parseus")
    print(f"Method: {config.method}")
    print(f"Docker Compose project: {config.project_name}")
    print(f"Integrations: {format_list(integrations)}")
    print(f"Public URL: {config.public_url}")
    print(f"Readiness endpoint: {config.health_host}:{config.https_port}")
    print(
        "Certificate source: "
        f"{'external' if uses_external_tls_certificates(config) else 'self-signed'}"
    )

    if uses_external_tls_certificates(config):
        print(f"Certificate file: {config.certificate_cert_file}")
        print(f"Private key file: {config.certificate_key_file}")
    else:
        print(f"Self-signed common name: {config.certificate_common_name}")
        print(f"Self-signed SAN DNS: {format_list(config.certificate_san_dns)}")
        print(f"Self-signed SAN IPs: {format_list(config.certificate_san_ips)}")
        print(f"Self-signed lifetime days: {config.certificate_days}")

    print(f"Compose override keys: {format_list(sorted(config.compose_env))}")
    known_compose_values = {
        key: config.compose_env[key]
        for key in sorted(
            {
                "PARSEUS_HTTP_BIND",
                "PARSEUS_HTTP_PORT",
                "PARSEUS_HTTPS_BIND",
                "PARSEUS_HTTPS_PORT",
            }
        )
        if key in config.compose_env
    }
    if known_compose_values:
        print("Known nginx Compose values:")
        for key, value in known_compose_values.items():
            print(f"  {key}={value}")

    print(f"Env override files: {format_list(sorted(config.env_overrides))}")
    if config.env_overrides:
        print("Env override keys:")
        for env_file, overrides in sorted(config.env_overrides.items()):
            print(f"  {env_file}: {format_list(sorted(overrides))}")

