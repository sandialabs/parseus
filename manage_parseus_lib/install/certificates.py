from __future__ import annotations

import tempfile
from pathlib import Path
from typing import List, Optional

from manage_parseus_lib.install.paths import InstallPaths
from manage_parseus_lib.config.model import InstallerConfig
from manage_parseus_lib.constants import DEFAULT_CMD_TIMEOUT
from manage_parseus_lib.file_ops import (
    atomic_write_bytes,
    backup_file_before_overwrite,
    ensure_directory,
)
from manage_parseus_lib.output import die, ok
from manage_parseus_lib.process import run
from manage_parseus_lib.system.permissions import set_config_file_permissions

def ensure_certs_dir(install_paths: InstallPaths) -> None:
    ensure_directory(install_paths.certs_dir, mode=0o750)

def uses_external_tls_certificates(config: InstallerConfig) -> bool:
    return (
        config.certificate_cert_file is not None
        or config.certificate_key_file is not None
    )

def prepare_nginx_tls_certificates(install_paths: InstallPaths, config: InstallerConfig) -> None:
    if uses_external_tls_certificates(config):
        install_external_nginx_certs(
            install_paths=install_paths,
            cert_file=config.certificate_cert_file,
            key_file=config.certificate_key_file,
            key_name="nginx-selfsigned.key",
            crt_name="nginx-selfsigned.crt",
        )
        return

    generate_self_signed_nginx_certs(
        install_paths=install_paths,
        common_name=config.certificate_common_name,
        san_dns=config.certificate_san_dns,
        san_ips=config.certificate_san_ips,
        days=config.certificate_days,
        key_name="nginx-selfsigned.key",
        crt_name="nginx-selfsigned.crt",
        overwrite=False,
    )

def install_external_nginx_certs(
    install_paths: InstallPaths,
    cert_file: Optional[Path],
    key_file: Optional[Path],
    key_name: str,
    crt_name: str,
) -> None:
    if cert_file is None or key_file is None:
        die("Both [certificates] cert_file and key_file are required for external TLS")

    cert_src = cert_file.expanduser()
    key_src = key_file.expanduser()
    cert_dst = install_paths.certs_dir / crt_name
    key_dst = install_paths.certs_dir / key_name

    validate_external_certificate_file(cert_src, "certificate")
    validate_external_certificate_file(key_src, "private key")
    ensure_certs_dir(install_paths)

    copy_tls_file_if_changed(cert_src, cert_dst, mode=0o644, label="certificate")
    copy_tls_file_if_changed(key_src, key_dst, mode=0o640, label="private key")
    ok(f"Installed external TLS certificate and key in {install_paths.certs_dir}")

def validate_external_certificate_file(path: Path, label: str) -> None:
    if not path.exists() or not path.is_file():
        die(f"External TLS {label} file not found: {path}")
    try:
        with path.open("rb") as f:
            f.read(1)
    except OSError as e:
        die(f"External TLS {label} file is not readable: {path}\nDetails: {e}")

def copy_tls_file_if_changed(src: Path, dst: Path, mode: int, label: str) -> None:
    new_data = src.read_bytes()
    backup_file_before_overwrite(dst, new_data, mode=0o600, label=dst.name)
    if dst.exists() and dst.is_file() and dst.read_bytes() == new_data:
        set_config_file_permissions(dst, mode=mode)
        ok(f"External TLS {label} already installed: {dst}")
        return

    atomic_write_bytes(dst, new_data, mode=mode)
    set_config_file_permissions(dst, mode=mode)
    ok(f"Wrote external TLS {label}: {dst}")

def generate_self_signed_nginx_certs(
    install_paths: InstallPaths,
    common_name: str = "localhost",
    san_dns: Optional[List[str]] = None,
    san_ips: Optional[List[str]] = None,
    days: int = 825,
    key_name: str = "nginx-selfsigned.key",
    crt_name: str = "nginx-selfsigned.crt",
    overwrite: bool = False,
) -> None:
    key_path = install_paths.certs_dir / key_name
    crt_path = install_paths.certs_dir / crt_name

    if not overwrite and key_path.exists() and crt_path.exists():
        ok(f"Certificates already exist: {key_path}, {crt_path} (skipping)")
        return

    ensure_certs_dir(install_paths)

    san_dns = san_dns or ["localhost"]
    san_ips = san_ips or ["127.0.0.1"]
    alt_name_lines = []
    for idx, name in enumerate(san_dns, start=1):
        alt_name_lines.append(f"DNS.{idx} = {name}")
    for idx, ip_value in enumerate(san_ips, start=1):
        alt_name_lines.append(f"IP.{idx} = {ip_value}")

    openssl_config = f"""
[req]
default_bits = 2048
prompt = no
default_md = sha256
x509_extensions = v3_req
distinguished_name = dn

[dn]
CN = {common_name}

[v3_req]
subjectAltName = @alt_names
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth

[alt_names]
{chr(10).join(alt_name_lines)}
"""

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as tmp:
            tmp.write(openssl_config)
            tmp_path = tmp.name

        cmd = [
            "openssl",
            "req",
            "-x509",
            "-nodes",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key_path),
            "-out",
            str(crt_path),
            "-days",
            str(days),
            "-config",
            tmp_path,
            "-extensions",
            "v3_req",
        ]

        r = run(cmd, timeout=DEFAULT_CMD_TIMEOUT)
        if not r.ok:
            die(f"OpenSSL certificate generation failed:\n{r.stderr or r.stdout}")

        set_config_file_permissions(key_path, 0o640)
        set_config_file_permissions(crt_path, 0o644)

    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

    ok(
        f"Generated self-signed certs in {install_paths.certs_dir}/ "
        f"(CN={common_name}, SAN DNS={san_dns}, SAN IPs={san_ips}, days={days})"
    )

