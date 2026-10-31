from __future__ import annotations

import hashlib
import json
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, cast

from manage_parseus_lib.config.model import InstallerConfig
from manage_parseus_lib.constants import MANIFEST_SCHEMA_VERSION
from manage_parseus_lib.docker.images import classify_images, remove_images, resolve_image_ids
from manage_parseus_lib.file_ops import atomic_write_text, ensure_directory

from manage_parseus_lib.install.paths import InstallPaths
from manage_parseus_lib.install.certificates import uses_external_tls_certificates
from manage_parseus_lib.output import die, info, ok
from manage_parseus_lib.system.permissions import set_state_file_permissions

from manage_parseus_lib.types import (
    InstallManifest,
    JsonValue,
    ManifestInstallerConfig,
    ManifestSystemAccounts,
)

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def ensure_state_dir(install_paths: InstallPaths) -> None:
    ensure_directory(install_paths.state_dir, mode=0o750)
    ensure_directory(install_paths.history_dir, mode=0o750)

def build_install_manifest(
    all_images: List[str],
    integrations: List[str],
    config: InstallerConfig,
    named_volumes: Optional[List[str]] = None,
    system_accounts: Optional[ManifestSystemAccounts] = None,
) -> InstallManifest:
    app_owned_images, dependency_images = classify_images(all_images)
    resolved_images = resolve_image_ids(all_images)
    manifest: InstallManifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "installed_at": utc_now_iso(),
        "app_version": resolve_app_version(config, app_owned_images),
        "integrations": sorted(set(integrations)),
        "all_images": sorted(set(all_images)),
        "app_owned_images": app_owned_images,
        "dependency_images": dependency_images,
        "resolved_images": resolved_images,
        "named_volumes": sorted(set(named_volumes or [])),
        "installer_config": build_manifest_installer_config(config),
    }
    if system_accounts is not None:
        manifest["system_accounts"] = system_accounts
    return manifest


def resolve_app_version(config: InstallerConfig, app_owned_images: List[str]) -> str:
    """Resolve the application version to record in the install manifest."""
    compose_version = str(config.compose_env.get("PARSEUS_VERSION", "")).strip()
    if compose_version:
        return compose_version

    for image_ref in sorted(app_owned_images):
        version = app_version_from_image_ref(image_ref)
        if version:
            return version

    return "unknown"


def app_version_from_image_ref(image_ref: str) -> str:
    """Return the tag from an app image reference, or an empty string."""
    without_digest = image_ref.split("@", 1)[0]
    repo, sep, tag = without_digest.rpartition(":")
    if not sep or "/" in tag or not repo:
        return ""
    return tag.strip()


def manifest_integrations_value(manifest: InstallManifest) -> object:
    """Return integration names from the install manifest."""
    return manifest.get("integrations", [])


def manifest_named_volumes_value(manifest: InstallManifest) -> List[str]:
    """Return Docker named volumes recorded in the install manifest."""
    value = manifest.get("named_volumes", [])
    if not isinstance(value, list):
        return []
    return sorted({item.strip() for item in value if isinstance(item, str) and item.strip()})

def build_manifest_installer_config(config: InstallerConfig) -> ManifestInstallerConfig:
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

    env_override_keys = {
        env_file: sorted(overrides)
        for env_file, overrides in sorted(config.env_overrides.items())
    }

    return {
        "config_file": str(config.config_file) if config.config_file else None,
        "app_root": "/opt/parseus",
        "config_root": "/etc/parseus",
        "data_root": "/var/lib/parseus",
        "log_root": "/var/log/parseus",
        "method": config.method,
        "project_name": config.project_name,
        "public_url": config.public_url,
        "health_host": config.health_host,
        "https_port": config.https_port,
        "certificate_common_name": config.certificate_common_name,
        "certificate_days": config.certificate_days,
        "certificate_san_dns": list(config.certificate_san_dns),
        "certificate_san_ips": list(config.certificate_san_ips),
        "certificate_source": (
            "external" if uses_external_tls_certificates(config) else "self_signed"
        ),
        "certificate_cert_file": (
            str(config.certificate_cert_file) if config.certificate_cert_file else None
        ),
        "certificate_key_file": (
            config.certificate_key_file.name if config.certificate_key_file else None
        ),
        "compose_env_keys": sorted(config.compose_env),
        "compose_env_fingerprint": stable_config_fingerprint(config.compose_env),
        "known_compose_values": known_compose_values,
        "env_override_files": sorted(config.env_overrides),
        "env_override_keys": env_override_keys,
        "env_overrides_fingerprint": stable_config_fingerprint(config.env_overrides),
    }

def stable_config_fingerprint(value: object) -> str:
    normalized = normalize_for_fingerprint(value)
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def normalize_for_fingerprint(value: object) -> JsonValue:
    if isinstance(value, dict):
        return {str(k): normalize_for_fingerprint(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_for_fingerprint(v) for v in value]
    if isinstance(value, tuple):
        return [normalize_for_fingerprint(v) for v in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)

def save_current_install_manifest(install_paths: InstallPaths, manifest: InstallManifest) -> None:
    if install_paths.current_manifest.exists():
        archive_current_manifest(install_paths)
    write_manifest(install_paths, manifest, install_paths.current_manifest)

def archive_current_manifest(install_paths: InstallPaths) -> None:
    if not install_paths.current_manifest.exists():
        return

    ensure_state_dir(install_paths)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    archive_path = install_paths.history_dir / f"manifest-{ts}.json"

    if archive_path.exists():
        suffix = secrets.token_hex(4)
        archive_path = install_paths.history_dir / f"manifest-{ts}-{suffix}.json"

    shutil.copy2(install_paths.current_manifest, archive_path)
    set_state_file_permissions(archive_path)
    ok(f"Archived previous manifest to {archive_path}")

def write_manifest(install_paths: InstallPaths, data: InstallManifest, path: Path) -> None:
    ensure_state_dir(install_paths)
    atomic_write_text(
        path, json.dumps(data, indent=2, sort_keys=True) + "\n", mode=0o640
    )
    set_state_file_permissions(path)
    ok(f"Wrote manifest: {path}")

def validate_manifest_schema(data: object, path: Path) -> None:
    if not isinstance(data, dict):
        die(f"Manifest {path} is invalid: expected a JSON object")

    version = data.get("schema_version")
    if version != MANIFEST_SCHEMA_VERSION:
        die(
            f"Manifest {path} has unsupported schema_version={version}. "
            f"Expected {MANIFEST_SCHEMA_VERSION}."
        )

def load_manifest(path: Path) -> Optional[InstallManifest]:
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        die(f"Failed to read manifest {path}: {e}")

    validate_manifest_schema(data, path)
    return cast(InstallManifest, data)

def remove_obsolete_manifest_images(
    old_manifest: Optional[InstallManifest], new_manifest: InstallManifest
) -> None:
    if not old_manifest:
        info("No previous manifest found; no obsolete images to remove")
        return

    old_ids = set(v for v in old_manifest.get("resolved_images", {}).values() if v)
    new_ids = set(v for v in new_manifest.get("resolved_images", {}).values() if v)
    obsolete_ids = sorted(old_ids - new_ids)

    if not obsolete_ids:
        info("No obsolete images from previous manifest to remove")
        return

    info("Removing obsolete images from previous manifest...")
    remove_images(obsolete_ids)

def purge_manifest_images(manifest: Optional[InstallManifest]) -> None:
    if not manifest:
        info("No manifest found; skipping removal of manifest-recorded images")
        return

    resolved_images = manifest.get("resolved_images", {})
    image_ids = sorted(set(v for v in resolved_images.values() if v))

    if image_ids:
        info("Removing all images recorded in manifest by exact image ID...")
        remove_images(image_ids)
        return

    info("No images found in manifest")

def manifests_differ_meaningfully(
    old_manifest: Optional[InstallManifest], new_manifest: InstallManifest
) -> bool:
    if old_manifest is None:
        return True

    keys_to_compare = [
        "schema_version",
        "app_version",
        "integrations",
        "all_images",
        "app_owned_images",
        "dependency_images",
        "resolved_images",
        "named_volumes",
        "installer_config",
    ]

    for key in keys_to_compare:
        old_value = (
            manifest_integrations_value(old_manifest)
            if key == "integrations"
            else old_manifest.get(key)
        )
        if old_value != new_manifest.get(key):
            return True

    return False

