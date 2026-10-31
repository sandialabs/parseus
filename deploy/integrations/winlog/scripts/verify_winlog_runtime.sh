#!/usr/bin/env bash
set -euo pipefail

COMPOSE_IMAGES="/var/lib/parseus/runtime/compose.images.yaml"
COMPOSE_RUNTIME="/var/lib/parseus/runtime/compose.runtime.yaml"
LOGSTASH_CONTAINER="parseus_logstash"
ELASTICSEARCH_CONTAINER="parseus_elasticsearch"
INIT_CONTAINER="parseus_elasticsearch_init"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      cat <<'EOF'
Usage:
  bash /opt/parseus/deploy/integrations/winlog/scripts/verify_winlog_runtime.sh

Checks that the Winlog integration containers are running, Logstash is healthy, and
shared runtime paths are present with the expected write posture.
EOF
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

FAILURES=0

pass() { echo "[PASS] $1"; }
fail() { echo "[FAIL] $1"; FAILURES=$((FAILURES + 1)); }

container_running() {
  local container="$1"
  docker ps --format '{{.Names}}' | grep -Fx "$container" >/dev/null 2>&1
}

check_container_running() {
  local container="$1"
  if container_running "$container"; then
    pass "$container is running"
  else
    fail "$container is not running"
  fi
}

check_one_shot_init() {
  local container="$1"
  if container_running "$container"; then
    pass "$container is running"
    return
  fi

  local exit_code
  exit_code=$(docker inspect -f '{{.State.ExitCode}}' "$container" 2>/dev/null || true)
  if [[ "$exit_code" == "0" ]]; then
    pass "$container completed successfully"
  else
    fail "$container is not running and has not completed successfully"
  fi
}

check_logstash_health() {
  if ! container_running "$LOGSTASH_CONTAINER"; then
    return
  fi

  if docker exec "$LOGSTASH_CONTAINER" sh -lc \
    "curl -fsS http://127.0.0.1:9600/_node/pipelines/main >/dev/null 2>&1 || wget -qO- http://127.0.0.1:9600/_node/pipelines/main >/dev/null 2>&1"; then
    pass "$LOGSTASH_CONTAINER pipeline API is healthy"
  else
    fail "$LOGSTASH_CONTAINER pipeline API is not healthy"
  fi
}

check_writable_path() {
  local container="$1"
  local path="$2"
  local marker="$path/.winlog_runtime_check.$$"

  if docker exec "$container" sh -lc "touch '$marker' && rm -f '$marker'" >/dev/null 2>&1; then
    pass "$container can write to $path"
  else
    fail "$container cannot write to $path"
  fi
}

check_readable_path() {
  local container="$1"
  local path="$2"

  if docker exec "$container" sh -lc "test -r '$path'" >/dev/null 2>&1; then
    pass "$container can read $path"
  else
    fail "$container cannot read $path"
  fi
}

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

echo "Validating Winlog runtime using managed Compose files: $COMPOSE_IMAGES, $COMPOSE_RUNTIME"

docker compose -f "$COMPOSE_IMAGES" -f "$COMPOSE_RUNTIME" --profile winlog ps >/dev/null 2>&1 || true

check_container_running "$ELASTICSEARCH_CONTAINER"
check_container_running "$LOGSTASH_CONTAINER"
check_one_shot_init "$INIT_CONTAINER"

if container_running "$LOGSTASH_CONTAINER"; then
  check_logstash_health
  check_writable_path "$LOGSTASH_CONTAINER" /usr/share/logstash/data
  check_readable_path "$LOGSTASH_CONTAINER" /usr/share/logstash/logs
fi

if [[ "$FAILURES" -gt 0 ]]; then
  printf '\nValidation completed with %s failure(s).\n' "$FAILURES" >&2
  exit 1
fi

printf '\nValidation completed successfully.\n'
exit 0
