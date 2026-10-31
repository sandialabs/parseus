#!/usr/bin/env bash
set -euo pipefail

COMPOSE_IMAGES="/var/lib/parseus/runtime/compose.images.yaml"
COMPOSE_RUNTIME="/var/lib/parseus/runtime/compose.runtime.yaml"
CONTAINER_NAME="parseus_gpib"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      cat <<'EOF'
Usage:
  bash /opt/parseus/deploy/integrations/gpib/scripts/verify_gpib_runtime.sh

Checks that the combined GPIB container is running in non-root mode and can
write to expected runtime paths.
EOF
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  echo "[FAIL] docker is not installed or not in PATH" >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "[FAIL] docker compose v2 is not available" >&2
  exit 1
fi

if [[ ! -f "$COMPOSE_IMAGES" || ! -f "$COMPOSE_RUNTIME" ]]; then
  echo "[FAIL] managed runtime compose files not found" >&2
  echo "       expected: $COMPOSE_IMAGES and $COMPOSE_RUNTIME" >&2
  exit 1
fi

FAILURES=0

pass() { echo "[PASS] $1"; }
fail() { echo "[FAIL] $1"; FAILURES=$((FAILURES + 1)); }

container_running() {
  local container="$1"
  docker ps --format '{{.Names}}' | grep -Fx "$container" >/dev/null 2>&1
}

check_non_root_user() {
  local container="$1"
  if ! container_running "$container"; then
    fail "$container is not running"
    return
  fi

  local uid
  uid=$(docker exec "$container" id -u 2>/dev/null || true)
  if [[ -z "$uid" ]]; then
    fail "$container user could not be determined"
    return
  fi

  if [[ "$uid" == "0" ]]; then
    fail "$container is running as root (uid=0)"
  else
    pass "$container is non-root (uid=$uid)"
  fi
}

check_writable_path() {
  local container="$1"
  local path="$2"
  local marker="$path/.gpib_runtime_check.$$"

  if docker exec "$container" sh -lc "touch '$marker' && rm -f '$marker'" >/dev/null 2>&1; then
    pass "$container can write to $path"
  else
    fail "$container cannot write to $path"
  fi
}

echo "Validating GPIB runtime using managed Compose files: $COMPOSE_IMAGES, $COMPOSE_RUNTIME"

docker compose -f "$COMPOSE_IMAGES" -f "$COMPOSE_RUNTIME" --profile gpib ps >/dev/null 2>&1 || true

check_non_root_user "$CONTAINER_NAME"

if container_running "$CONTAINER_NAME"; then
  check_writable_path "$CONTAINER_NAME" /home/webapp/.parseus/artifacts/logs
  check_writable_path "$CONTAINER_NAME" /home/webapp/.parseus/artifacts/pcaps
fi

if [[ "$FAILURES" -gt 0 ]]; then
  printf '\nValidation completed with %s failure(s).\n' "$FAILURES" >&2
  exit 1
fi

printf '\nValidation completed successfully.\n'
exit 0
