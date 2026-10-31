# GPIB Ingestor (Parseus Optional Integration)

This directory contains the optional GPIB ingestion component used by Parseus when the `gpib` integration is enabled.

The runtime process is:

- `parseus.ingestors.gpib.parser` (single combined listener/parser/indexer process)

## Scope and Runtime Behavior

`parseus.ingestors.gpib.parser` handles all of the following in one process:

- validated environment-driven configuration
- TCP connection and reconnect loop to the GPIB-over-Ethernet endpoint
- graceful SIGTERM/SIGINT shutdown with final buffer flush
- payload decoding and normalization
- datastore indexing (`<INGESTOR_INDEX>-YYYY-MM-DD`)
- local date-partitioned NDJSON capture file output using atomic file replacement
- rotating file logs plus stdout/stderr logs for container observability

## Directory Layout

```text
deploy/integrations/gpib/
├─ README.md
└─ scripts/
   ├─ pcap_replay.py
   ├─ setup_listener.py
   └─ verify_gpib_runtime.sh
```

## Compose Integration

In `compose.runtime.yaml`, service `gpib` is configured with:

- container name `parseus_gpib`
- command `python -m parseus.ingestors.gpib.parser`
- `network_mode: host`
- env files: `envs/datastore.env`, `envs/ingestor.env`
- writable Docker volumes for logs and captures under `/home/webapp/.parseus/artifacts/`
- bounded Docker JSON-file logging
- a container health check that verifies the parser process is active

The Parseus application image runs as the non-root `webapp` user, so the GPIB process should not run as root.

Start Parseus with the GPIB integration/profile enabled:

```bash
sudo manage-parseus up --integrations gpib
```

Equivalent direct compose invocation using the managed runtime Compose files:

```bash
sudo docker compose --env-file /etc/parseus/compose.env -f /var/lib/parseus/runtime/compose.images.yaml -f /var/lib/parseus/runtime/compose.runtime.yaml --profile gpib up -d
```

## Controller Setup (Prologix GPIB-ETHERNET)

If you are using a Prologix bridge, configure it for listener-only operation before enabling ingestion.

Helper script:

```bash
python deploy/integrations/gpib/scripts/setup_listener.py --host <device_ip> --port <device_port>
```

The script requires an explicit `--host`, uses a socket timeout, sends newline-terminated ASCII commands, and configures the bridge for listener-only mode.

## Runtime Validation

After startup, validate the GPIB container runtime posture:

```bash
bash /opt/parseus/deploy/integrations/gpib/scripts/verify_gpib_runtime.sh
```

Checks performed:

- `parseus_gpib` container is running
- container runs as non-root
- expected log/capture paths are writable

## Local Development / Test

Replay test traffic from a PCAP file:

```bash
python deploy/integrations/gpib/scripts/pcap_replay.py -f <path/to/pcap> --host 127.0.0.1 -p 1234
```

Run parser directly (for local development):

```bash
PYTHONPATH=src python -m parseus.ingestors.gpib.parser
```

> `pcap_replay.py` depends on `scapy`.

## Configuration

Main environment variables (normally provided via `envs/ingestor.env`):

- `DATASTORE_HOST_URL`
- `DATASTORE_TYPE` (`elasticsearch` or `opensearch`)
- `DATASTORE_AUTH` (optional)
- `INGESTOR_INDEX`
- `INGESTOR_GPIB_IP`
- `INGESTOR_GPIB_PORT`
- `INGESTOR_GPIB_SOCKET_TIMEOUT`
- `INGESTOR_GPIB_RECONNECT_DELAY_BASE`
- `INGESTOR_GPIB_RECONNECT_DELAY_MAX`
- `INGESTOR_RECV_BUFFER_SIZE`
- `INGESTOR_MAX_EVENTS_PER_FLUSH`
- `INGESTOR_IDLE_FLUSH_SECONDS`
- `INGESTOR_FLUSH_CHECK_INTERVAL`
- `INGESTOR_CAPTURE_DIR` (defaults to `/home/webapp/.parseus/artifacts/pcaps` in the container and must be writable)
- `INGESTOR_LOG_FILE` (optional override for the parser log path)
- `LOG_LEVEL`
- `LOG_MAX_BYTES`
- `LOG_BACKUP_COUNT`

Capture files are written as date-partitioned NDJSON:

- `<INGESTOR_CAPTURE_DIR>/<YYYY>/<MM>/<DD>/capture_<n>.ndjson`

Each flush writes to a temporary file first and then atomically renames it to the final `.ndjson` name so downstream readers do not observe partial files.

## Logs and Data Handling

Default runtime paths in the Parseus container:

- logs: `/home/webapp/.parseus/artifacts/logs/gpib_parser.log`
- captures: `/home/webapp/.parseus/artifacts/pcaps/...`

Treat both logs and captures as sensitive operational data.

## Production best practices

### Network and access design

- Keep the GPIB bridge in listener-only mode.
- Restrict network access to the bridge and Parseus host.
- Prefer a dedicated management network for the bridge when possible.
- Use least-privilege datastore credentials.

### Data handling

- Treat logs and captures as sensitive operational data.
- Apply retention, backup, and secure deletion policies for captured payload data.
- Monitor free space for the `pcap_data` volume because captures are intentionally persisted.

### Operations

- Run `scripts/verify_gpib_runtime.sh` after install, restart, and upgrades.
- Alert on stale `scpi_parsed-*` ingestion using the configured GPIB health thresholds.
- Keep bridge firmware, Docker images, and the Parseus host OS current through the standard maintenance process.