"""Idempotently configure Elasticsearch retention for the winlog integration."""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

ES_URL = os.environ.get("ELASTICSEARCH_URL", "http://elasticsearch:9200").rstrip("/")
POLICY_NAME = os.environ.get("WINLOG_ILM_POLICY_NAME", "delete-after-90d")
TEMPLATE_NAME = os.environ.get(
    "WINLOG_INDEX_TEMPLATE_NAME", "winlogbeat-delete-template"
)
INDEX_PATTERN = os.environ.get("WINLOG_INDEX_PATTERN", "winlogbeat-*")
RETENTION_AGE = os.environ.get("WINLOG_RETENTION_AGE", "90d")
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("ELASTICSEARCH_REQUEST_TIMEOUT", "10"))
WAIT_TIMEOUT_SECONDS = float(os.environ.get("ELASTICSEARCH_WAIT_TIMEOUT", "300"))
WAIT_INTERVAL_SECONDS = float(os.environ.get("ELASTICSEARCH_WAIT_INTERVAL", "5"))


def auth_header() -> dict[str, str]:
    username = os.environ.get("ELASTICSEARCH_USERNAME")
    password = os.environ.get("ELASTICSEARCH_PASSWORD")
    if not username or not password:
        return {}

    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def request(
    url: str, method: str = "GET", payload: dict[str, Any] | None = None
) -> tuple[int, str]:
    headers = {**auth_header()}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def wait_for_es() -> None:
    print(f"Waiting up to {WAIT_TIMEOUT_SECONDS:.0f}s for Elasticsearch at {ES_URL}...")
    deadline = time.monotonic() + WAIT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            status, _body = request(ES_URL)
            if status == 200:
                print("Elasticsearch is up.")
                return
        except Exception as exc:
            print(f"Elasticsearch not ready yet: {exc}")
        time.sleep(WAIT_INTERVAL_SECONDS)

    raise TimeoutError(
        f"Elasticsearch did not become ready within {WAIT_TIMEOUT_SECONDS:.0f}s"
    )


def put_json(path: str, payload: dict[str, Any]) -> None:
    url = f"{ES_URL}{path}"
    status, body = request(url, method="PUT", payload=payload)
    print(f"PUT {url} -> {status}")
    print(body)
    if status >= 400:
        raise RuntimeError(f"PUT {url} failed with status {status}")


def get(path: str) -> tuple[int, str]:
    return request(f"{ES_URL}{path}")


def build_policy() -> dict[str, Any]:
    return {
        "policy": {
            "phases": {
                "hot": {"actions": {}},
                "delete": {"min_age": RETENTION_AGE, "actions": {"delete": {}}},
            }
        }
    }


def build_template() -> dict[str, Any]:
    return {
        "index_patterns": [INDEX_PATTERN],
        "template": {"settings": {"index.lifecycle.name": POLICY_NAME}},
    }


def main() -> int:
    wait_for_es()

    print("Creating/updating ILM policy...")
    put_json(f"/_ilm/policy/{POLICY_NAME}", build_policy())

    print("Creating/updating index template...")
    put_json(f"/_index_template/{TEMPLATE_NAME}", build_template())

    print("Checking for existing indices...")
    status, body = get(f"/_cat/indices/{INDEX_PATTERN}?h=index")
    if status == 200 and body.strip():
        print("Applying policy to existing indices...")
        settings = {"index": {"lifecycle": {"name": POLICY_NAME}}}
        put_json(f"/{INDEX_PATTERN}/_settings", settings)
    else:
        print("No existing indices found.")

    print("Current matching indices:")
    _status, body = get(f"/_cat/indices/{INDEX_PATTERN}?v")
    print(body)
    print("Done.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
