# Windows Logstash Ingestion Integration

This optional integration adds a production-oriented ingestion path for Windows event data that is staged as files and indexed into the Parseus Elasticsearch datastore.

It is intended for environments where Windows/Sysmon/Winlogbeat telemetry is exported as newline-delimited JSON (`*.ndjson`) files, placed in a host drop directory, and consumed by Parseus. No special transfer hardware is required; any reliable process that writes complete `*.ndjson` files into the configured directory can be used.

## How this fits into Parseus

Parseus can run with only its core application services, but the `winlog` integration enables an additional Windows event ingestion pipeline. The `winlog` integration enables the Docker Compose profile for this pipeline.

1. A Windows collection side exports Winlogbeat-compatible events as `*.ndjson` files.
2. A file transfer, sync, or staging process places those files in the Parseus drop directory.
3. The optional Logstash container reads completed `*.ndjson` files from that directory.
4. Logstash parses each JSON event and writes it to Elasticsearch as daily `winlogbeat-YYYY.MM.DD` indices.
5. Parseus analytics and host-anomaly features query the `winlogbeat-*` index pattern.
6. A one-shot Elasticsearch initialization job installs the Index Lifecycle Management (ILM) policy that deletes matching indices after 90 days.
7. Parseus maintenance tasks monitor ingestion freshness and remove files after Logstash records them as completed.

This keeps Parseus responsible for indexing, analytics, retention, and monitoring while allowing Windows event collection and file transfer to remain external operational concerns.

## Files in this integration

| Path | Purpose |
| --- | --- |
| `logstash/pipeline/logstash.conf` | Logstash pipeline. Reads `/usr/share/logstash/logs/*.ndjson`, decodes JSON, writes valid events to `winlogbeat-%{+yyyy.MM.dd}` indices, and stores JSON parse failures in a rejected-events file. |
| `logstash/config/logstash.yml` | Logstash runtime configuration. Points Logstash at the pipeline directory, enables persistent queues and dead-letter queues, disables automatic config reload, and uses warn-level logging. |
| `logstash/data/.gitignore` | Keeps Logstash runtime state out of source control. |
| `elasticsearch/init_ilm.py` | Idempotent setup script that waits for Elasticsearch with a finite timeout, creates/updates a retention ILM policy, creates/updates an index template for `winlogbeat-*`, and applies the policy to existing matching indices. |
| `scripts/verify_winlog_runtime.sh` | Operator verification helper for container health and required runtime paths. |

Runtime files created under `logstash/data/` include:

- `files.sincedb` — Logstash file input read offsets.
- `completed-files.log` — list of files Logstash has finished processing.
- `rejected-events.ndjson` — malformed JSON events that should be investigated and fixed upstream.
- Logstash persistent queue and dead-letter queue files.

These files are operational state and should not be committed.

## Directory Layout

```text
deploy/integrations/winlog/
├─ README.md
├─ elasticsearch/
│  └─ init_ilm.py
├─ logstash/
│  ├─ config/
│  │  └─ logstash.yml
│  ├─ data/
│  │  └─ .gitignore
│  └─ pipeline/
│     └─ logstash.conf
└─ scripts/
   └─ verify_winlog_runtime.sh
```

## Runtime architecture

When the `winlog` integration is enabled, `compose.runtime.yaml` adds or connects the following services:

- `logstash` runs the pipeline in `logstash/pipeline/logstash.conf`.
- `elasticsearch` stores the indexed Windows event data.
- `elasticsearch-init` runs `elasticsearch/init_ilm.py` once at stack startup to enforce retention.
- `scheduler` reads `completed-files.log`, cleans processed files from the drop directory, and checks Logstash ingestion freshness.
- `beat` schedules the maintenance tasks.
- `web` exposes Parseus analytics and monitoring views.

The default drop directory is controlled by `PARSEUS_FTP_HOST_DIR` and defaults to:

```text
/srv/parseus/ftp
```

That directory is mounted as:

- `/usr/share/logstash/logs` inside the Logstash container.
- `/ftp` inside the scheduler container.

The shared Logstash state directory is mounted read/write into Logstash and read-only into the scheduler so the scheduler can safely read `completed-files.log`.

Runtime hardening includes read-only mounts for bundled Logstash pipeline/config and Elasticsearch setup code, writable mounts only for ingestion drop/state paths, persistent Logstash queues with a configured size limit, explicit container health checks, and a one-shot ILM setup container that can be rerun safely.

## Data flow

```text
Windows telemetry / Winlogbeat export
        |
        v
File transfer, sync job, or staging process
        |
        v
PARSEUS_FTP_HOST_DIR on the Parseus host
        |
        v
Logstash file input: /usr/share/logstash/logs/*.ndjson
        |
        v
Elasticsearch indices: winlogbeat-YYYY.MM.DD
        |
        v
Parseus analytics, dashboards, and ingestor health checks
```

## Enabling the integration

Install Parseus with the Windows Logstash ingestion integration:

```bash
sudo manage-parseus install --integrations winlog
```

Enable it together with the GPIB integration:

```bash
sudo manage-parseus install --integrations gpib,winlog
```

For an existing installation, restart or upgrade with the integration enabled:

```bash
sudo manage-parseus restart --integrations winlog
```

If you need to place the drop directory somewhere other than the default, set `PARSEUS_FTP_HOST_DIR` through the installer configuration `[compose]` section or in the environment used by direct Docker Compose commands:

```ini
[compose]
PARSEUS_FTP_HOST_DIR = /srv/parseus/ftp
```

Use a dedicated filesystem or volume for this directory in production so ingestion bursts cannot exhaust the root filesystem.

## Input format requirements

The pipeline expects files matching:

```text
*.ndjson
```

Each line must be a complete JSON object compatible with the fields expected by the Parseus Windows/Sysmon analytics. Events should include a valid `@timestamp` field so Elasticsearch indexing, freshness checks, and time-based analytics work correctly.

Operational recommendations:

- Write files atomically. Transfer to a temporary name and rename to `*.ndjson` only after the file is complete.
- Avoid modifying a file after Logstash starts reading it.
- Keep filenames unique to prevent confusion during cleanup and incident review.
- Validate JSON before transfer whenever possible.
- Size batches so Logstash can process them within the configured freshness thresholds.

## Retention and ILM

`elasticsearch/init_ilm.py` creates these Elasticsearch resources:

- ILM policy: `delete-after-90d`
- Index template: `winlogbeat-delete-template`
- Index pattern: `winlogbeat-*`

The policy has a hot phase and a delete phase. Indices matching `winlogbeat-*` are deleted after 90 days.

The setup script is safe to run repeatedly. On startup it:

1. Waits for Elasticsearch to respond.
2. Creates or updates the ILM policy.
3. Creates or updates the index template for future `winlogbeat-*` indices.
4. Applies the lifecycle policy to existing matching indices when any exist.

For production, confirm that 90 days satisfies your regulatory, audit, and incident-response requirements before enabling the pipeline. If your organization requires a different retention period, set `WINLOG_RETENTION_AGE` and, when appropriate, `WINLOG_ILM_POLICY_NAME` consistently and document the change in deployment records.

Supported ILM setup environment overrides include:

- `ELASTICSEARCH_URL`
- `ELASTICSEARCH_USERNAME`
- `ELASTICSEARCH_PASSWORD`
- `ELASTICSEARCH_WAIT_TIMEOUT`
- `WINLOG_ILM_POLICY_NAME`
- `WINLOG_INDEX_TEMPLATE_NAME`
- `WINLOG_INDEX_PATTERN`
- `WINLOG_RETENTION_AGE`

## Maintenance and monitoring

Parseus includes scheduled maintenance tasks that support this integration:

- `check-logstash-ingestor-health` runs every 5 minutes and checks the newest event in `winlogbeat-*`.
- `run-cleanup-ftp-files` runs hourly and removes files from the drop directory after Logstash lists them in `completed-files.log`.

The default Logstash freshness thresholds are managed through the ingestor health environment:

- `LOGSTASH_HEALTH_INDEX_PATTERN=winlogbeat-*`
- `LOGSTASH_WARN_AFTER_SECONDS=600`
- `LOGSTASH_CRITICAL_AFTER_SECONDS=1200`

Tune these values to match expected event arrival cadence. A batch-oriented deployment with infrequent file drops should use larger thresholds than a near-real-time deployment.

## Verification

After starting Parseus with `--integrations winlog`, run the bundled verification helper:

```bash
bash /opt/parseus/deploy/integrations/winlog/scripts/verify_winlog_runtime.sh
```

You can also verify the stack manually:

```bash
docker ps --filter name=parseus_logstash
docker ps --filter name=parseus_elasticsearch
docker ps --filter name=parseus_elasticsearch_init
```

Check Logstash health:

```bash
docker inspect --format='{{json .State.Health}}' parseus_logstash
```

Confirm Elasticsearch indices are being created:

```bash
docker exec parseus_elasticsearch curl -s 'http://localhost:9200/_cat/indices/winlogbeat-*?v'
```

Confirm the ILM policy exists:

```bash
docker exec parseus_elasticsearch curl -s 'http://localhost:9200/_ilm/policy/delete-after-90d?pretty'
```

Confirm matching indices have lifecycle settings:

```bash
docker exec parseus_elasticsearch curl -s 'http://localhost:9200/winlogbeat-*/_settings?pretty'
```

## Production best practices

### Network and access design

- Keep Elasticsearch and Kibana on the internal Docker network or behind the Parseus reverse proxy; do not expose Elasticsearch directly to untrusted networks.
- Treat the drop directory as controlled ingest storage. Only the transfer process and Parseus services should have access.
- Use host firewall rules to restrict any exposed ingestion or management ports to approved systems.
- If deploying outside an isolated environment, enable Elasticsearch security and TLS, or place the stack behind equivalent network controls.

### File handling

- Use atomic file delivery: upload or copy as `filename.tmp`, verify integrity, then rename to `filename.ndjson`.
- Ensure the transferring account can write to the drop directory but cannot modify Parseus application files.
- Monitor available disk space in the drop directory and Elasticsearch data volume.
- Keep Logstash runtime state persistent so restarts do not reprocess already consumed files.

### Data quality

- Ensure each event is valid JSON and includes `@timestamp`.
- Keep source host, user, process, and event identifiers consistent with Winlogbeat/Sysmon conventions expected by analytics.
- Consider validating or sampling incoming files before production cutover.

### Retention and capacity

- Size the Elasticsearch volume for at least 90 days of expected indexed data plus operational headroom.
- Track ingestion rate, index size, heap usage, and disk watermarks.
- Review the 90-day ILM policy against operational and compliance requirements.
- Use dedicated storage for Elasticsearch data in production.

### Operations

- Back up configuration and deployment manifests; do not rely on the ingestion drop directory as durable storage.
- Alert on failed Logstash health checks, stale `winlogbeat-*` data, Elasticsearch disk pressure, growing persistent/dead-letter queues, and repeated JSON parse failures.
- Test restore and upgrade procedures before production changes.
- Keep Docker images, host OS packages, and certificates current through the standard Parseus upgrade process.

## Troubleshooting

### No `winlogbeat-*` indices appear

- Confirm the `winlog` integration is enabled.
- Confirm `parseus_logstash` is running and healthy.
- Confirm `*.ndjson` files exist in `PARSEUS_FTP_HOST_DIR`.
- Confirm files contain valid line-delimited JSON.
- Check Logstash logs:

```bash
docker logs parseus_logstash --tail 200
```

### Files are not cleaned up

- Confirm `completed-files.log` exists under `/var/lib/parseus/winlog/logstash/` on the Parseus host.
- Confirm the scheduler container is running.
- Confirm `PARSEUS_FTP_HOST_DIR` points to the same host directory used by the transfer process.
- Check scheduler logs for `cleanup_ftp_files` messages.

### ILM policy is missing

- Confirm `parseus_elasticsearch_init` ran after Elasticsearch became healthy.
- Re-run the stack or run the script from the installed setup directory.
- Check init logs:

```bash
docker logs parseus_elasticsearch_init
```

### Events are stale or health is critical

- Confirm new data is being delivered within the configured freshness threshold.
- Confirm events include correct `@timestamp` values and time zones.
- Increase `LOGSTASH_WARN_AFTER_SECONDS` and `LOGSTASH_CRITICAL_AFTER_SECONDS` if the deployment is intentionally batch-oriented.

## Security note

The default Parseus Compose configuration is suitable for a standalone controlled deployment. Before operating in a broader production network, review Elasticsearch security, TLS, host firewall rules, user permissions on the drop directory, backup requirements, and retention obligations with your operations and security teams.
