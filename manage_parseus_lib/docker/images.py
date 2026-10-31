from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from manage_parseus_lib.constants import DEFAULT_CMD_TIMEOUT, LONG_CMD_TIMEOUT
from manage_parseus_lib.docker.compose import compose_base_cmd, compose_env_file_args
from manage_parseus_lib.install.paths import InstallPaths
from manage_parseus_lib.output import die, info, ok
from manage_parseus_lib.process import run, run_streaming


def prepare_images(install_paths: InstallPaths, method: str) -> None:
    if method == "repository":
        build_docker_images(install_paths)
        pull_docker_images(install_paths)
    else:
        load_offline_images(install_paths.images_dir)


def build_docker_images(install_paths: InstallPaths) -> None:
    info("Building Docker images. This may take several minutes.")
    info("Showing the latest Docker build status; long-running steps are normal.")
    cmd = (
        compose_base_cmd(install_paths.project_name)
        + compose_env_file_args(install_paths)
        + [
            "-f",
            str(install_paths.build_compose),
            "build",
            "--progress",
            "plain",
        ]
    )

    r = run_streaming(
        cmd,
        timeout=LONG_CMD_TIMEOUT,
        heartbeat_message="Docker build is still running",
    )
    if not r.ok:
        die(
            f"Failed to build docker images:\nCommand: {' '.join(cmd)}\n\n"
            f"{r.stderr or r.stdout}"
        )

    ok("Built docker images.")


def pull_docker_images(install_paths: InstallPaths) -> None:
    info("Pulling Docker images...")
    info(
        "Showing the latest Docker pull status; "
        "large images may take a while to download."
    )

    cmd = (
        compose_base_cmd(install_paths.project_name)
        + compose_env_file_args(install_paths)
        + [
            "-f",
            str(install_paths.images_compose),
            "pull",
        ]
    )

    r = run_streaming(
        cmd,
        timeout=LONG_CMD_TIMEOUT,
        heartbeat_message="Docker image pull is still running",
    )
    if not r.ok:
        die(
            f"Failed to pull docker images:\nCommand: {' '.join(cmd)}\n\n"
            f"{r.stderr or r.stdout}"
        )

    ok("Pulled docker images.")


def load_offline_images(images_dir: Path) -> None:
    if not images_dir.exists() or not images_dir.is_dir():
        die(f"Images folder not found: {images_dir.resolve()}")

    patterns = ("*.tar", "*.tgz", "*.tar.gz")
    archives = []
    for pattern in patterns:
        archives.extend(sorted(images_dir.glob(pattern)))

    if not archives:
        die(
            f"No image archives found in {images_dir.resolve()} "
            "(expected .tar/.tgz/.tar.gz)"
        )

    info(f"Loading {len(archives)} image archive(s) from {images_dir.resolve()}...")
    for archive in archives:
        info(f"Loading: {archive.name}")
        r = run_streaming(
            ["docker", "load", "-i", str(archive)],
            timeout=LONG_CMD_TIMEOUT,
            heartbeat_message=f"Loading {archive.name} is still running",
        )
        if not r.ok:
            die(f"Failed to load image archive {archive.name}:\n{r.stderr or r.stdout}")
        ok(f"Loaded {archive.name}")


def list_local_images() -> List[str]:
    r = run(
        ["docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}"],
        timeout=DEFAULT_CMD_TIMEOUT,
    )
    if not r.ok or not r.stdout:
        return []

    images = []
    for line in r.stdout.splitlines():
        value = line.strip()
        if value and value != "<none>:<none>":
            images.append(value)
    return sorted(set(images))


def find_similar_local_images(image_ref: str, local_images: List[str]) -> List[str]:
    repo = image_ref.split("@", 1)[0].split(":", 1)[0]
    matches = []

    for local in local_images:
        local_repo = local.split(":", 1)[0]
        if (
            local == image_ref
            or local_repo == repo
            or repo in local_repo
            or local_repo in repo
        ):
            matches.append(local)

    return sorted(set(matches))[:10]


def verify_required_images(required: List[str]) -> None:
    missing = [image for image in required if get_image_id(image) is None]
    if not missing:
        ok("All required images are present")
        return

    local_images = list_local_images()

    lines = ["Missing required Docker images after image build/pull/load:"]
    for image in missing:
        lines.append(f"  - {image}")
        similar = find_similar_local_images(image, local_images)
        if similar:
            lines.append("    Similar local images found:")
            for candidate in similar:
                lines.append(f"      * {candidate}")

    lines.append(
        "Ensure your repository build/pull or offline archives contain these exact tags."
    )
    die("\n".join(lines))


def remove_images(image_ids: List[str]) -> None:
    if not image_ids:
        info("No image IDs to remove")
        return

    seen = set()
    unique_ids = []
    for image_id in image_ids:
        if not image_id:
            continue
        image_id = image_id.strip()
        if not image_id or image_id in seen:
            continue
        seen.add(image_id)
        unique_ids.append(image_id)

    if not unique_ids:
        info("No valid image IDs to remove")
        return

    info(f"Removing {len(unique_ids)} Docker image(s) by exact image ID...")

    for image_id in unique_ids:
        r = run(["docker", "image", "rm", image_id], timeout=LONG_CMD_TIMEOUT)
        if not r.ok:
            info(
                f"Could not remove image ID {image_id}; "
                f"it may still be referenced: {r.stderr or r.stdout}"
            )
        else:
            ok(f"Removed image ID: {image_id}")


def classify_images(images: List[str]) -> Tuple[List[str], List[str]]:
    app_owned = []
    dependency = []

    for image in images:
        if is_app_owned_image(image):
            app_owned.append(image)
        else:
            dependency.append(image)

    return sorted(set(app_owned)), sorted(set(dependency))


def is_app_owned_image(image_ref: str) -> bool:
    repo = image_ref.split(":", 1)[0]
    return (
        repo == "parseus" or repo.startswith("parseus-") or repo.startswith("parseus/")
    )


def get_image_id(image_ref: str) -> Optional[str]:
    r = run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image_ref],
        timeout=DEFAULT_CMD_TIMEOUT,
    )
    if not r.ok or not r.stdout:
        return None
    return r.stdout.strip()


def resolve_image_ids(images: List[str]) -> Dict[str, str]:
    resolved = {}
    for image in images:
        image_id = get_image_id(image)
        if image_id:
            resolved[image] = image_id
    return resolved
