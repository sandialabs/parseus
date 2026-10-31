#!/usr/bin/env python3
"""Add test alerts to a Parseus Elasticsearch datastore.

This script is intentionally dependency-free and targets the Parseus standalone
runtime default nginx Elasticsearch proxy at https://localhost/elasticsearch/.
Run it multiple times to add more unique unhandled alerts for the Alerts page.
"""

from __future__ import annotations

import argparse
import base64
import json
import random
import ssl
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

DEFAULT_URL = "https://localhost/elasticsearch/"

ALERT_AGENTS = {
    "scpi_range": ["ScpiValueRangesAnalytic", "ScpiCompareAnalytic"],
    "device": ["SysmonUnapprovedDeviceAnalytic", "SysmonUnapprovedIpAnalytic", "SysmonUnapprovedUserAnalytic"],
}

SAMPLE_MESSAGES = {
    "scpi_range": [
        "Manual test: bench power supply voltage exceeded expected range on channel 2.",
        "Manual test: oscilloscope acquisition rate dropped below operational threshold.",
        "Manual test: temperature chamber setpoint mismatch persisted across repeated reads.",
        "Manual test: signal generator frequency drift detected outside tolerance.",
    ],
    "device": [
        "Manual test: unexpected outbound connection from HMI workstation to external host.",
        "Manual test: privileged account interactive session outside maintenance window.",
        "Manual test: unsigned driver loaded on engineering workstation.",
        "Manual test: process creation from removable media detected on operator station.",
    ],
}


def utc_now_z() -> str:
    """Return the current UTC time in Elasticsearch-friendly ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def current_alert_index(prefix: str) -> str:
    """Return today's alert index name using the Parseus alerts-* convention."""
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y.%m.%d')}"


def choose_alert_type(requested: str) -> str:
    if requested == "random":
        return random.choice(list(ALERT_AGENTS.keys()))
    return requested


def build_alert(alert_type: str, message: str | None = None) -> dict[str, object]:
    """Build one unhandled alert document recognized by the Alerts page filters."""
    alert_uuid = str(uuid.uuid4())
    agent_type = random.choice(ALERT_AGENTS[alert_type])
    alert_message = message or random.choice(SAMPLE_MESSAGES[alert_type])

    return {
        "@timestamp": utc_now_z(),
        "handled": False,
        "agent": {
            "type": agent_type,
        },
        "event": {
            "uuid": alert_uuid,
            "kind": "alert",
            "category": ["intrusion_detection"],
            "type": ["info"],
            "original": f"{alert_message} UUID={alert_uuid}",
        },
        "acknowledge": {
            "reason": "none",
            "timestamp": None,
        },
        "rule": {
            "name": "Manual Parseus test alert",
        },
        "observer": {
            "name": "extras/add_test_alert.py",
        },
        "tags": ["manual-test", "parseus-alert-page"],
        "message": alert_message,
    }


def make_request(
    url: str,
    payload: dict[str, object],
    verify_tls: bool,
    username: str | None = None,
    password: str | None = None,
) -> dict[str, object]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    if username is not None and password is not None:
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode(
            "ascii"
        )
        request.add_header("Authorization", f"Basic {token}")

    context = None if verify_tls else ssl._create_unverified_context()
    with urllib.request.urlopen(request, context=context, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add one or more manual test alerts to Parseus Elasticsearch."
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"Elasticsearch base URL. Default: {DEFAULT_URL}",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of alerts to add. Default: 1",
    )
    parser.add_argument(
        "--type",
        choices=["scpi_range", "device", "random"],
        default="random",
        help="Alert section/type to create. Default: random",
    )
    parser.add_argument(
        "--index-prefix",
        default="alerts",
        help="Alert index prefix. Default creates alerts-YYYY.MM.DD",
    )
    parser.add_argument(
        "--message",
        help="Custom event.original/message text to use for every created alert.",
    )
    parser.add_argument(
        "--username",
        help="Optional basic-auth username if your datastore proxy requires it.",
    )
    parser.add_argument(
        "--password",
        help="Optional basic-auth password if your datastore proxy requires it.",
    )
    parser.add_argument(
        "--verify-tls",
        action="store_true",
        help="Verify TLS certificates. By default verification is disabled for localhost self-signed certs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print documents instead of sending them.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.count < 1:
        print("--count must be at least 1", file=sys.stderr)
        return 2

    index = current_alert_index(args.index_prefix)
    base_url = args.url.rstrip("/")

    created = 0
    for _ in range(args.count):
        alert_type = choose_alert_type(args.type)
        alert = build_alert(alert_type, args.message)
        alert_uuid = alert["event"]["uuid"]
        endpoint = f"{base_url}/{index}/_doc/{alert_uuid}?refresh=true"

        if args.dry_run:
            print(json.dumps({"url": endpoint, "document": alert}, indent=2))
            created += 1
            continue

        try:
            response = make_request(
                endpoint,
                alert,
                verify_tls=args.verify_tls,
                username=args.username,
                password=args.password,
            )
        except urllib.error.HTTPError as err:
            body = err.read().decode("utf-8", errors="replace")
            print(f"Failed to add alert: HTTP {err.code} {err.reason}\n{body}", file=sys.stderr)
            return 1
        except Exception as err:
            print(f"Failed to add alert: {type(err).__name__}: {err}", file=sys.stderr)
            return 1

        created += 1
        result = response.get("result", "unknown")
        print(
            f"Added {alert_type} alert {alert_uuid} to {index} "
            f"with agent.type={alert['agent']['type']} ({result})."
        )

    print(f"Done. Added {created} alert(s). Refresh the Alerts page or wait for the stream to update.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
