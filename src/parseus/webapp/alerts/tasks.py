import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import redis
from celery import shared_task
from django.conf import settings

from parseus.interfaces.common import get_ds_client
from parseus.util.datetime_utils import datetime_parser

logger = logging.getLogger(__name__)

redis_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
redis_client = redis.from_url(redis_url, decode_responses=True)

INGESTOR_HEALTH_REDIS_PREFIX = os.getenv(
    "INGESTOR_HEALTH_REDIS_PREFIX", "health:ingestor"
)

LOGSTASH_HEALTH_INDEX_PATTERN = os.getenv(
    "LOGSTASH_HEALTH_INDEX_PATTERN", "winlogbeat-*"
)
LOGSTASH_WARN_AFTER_SECONDS = int(
    os.getenv("LOGSTASH_WARN_AFTER_SECONDS", str(10 * 60))
)
LOGSTASH_CRITICAL_AFTER_SECONDS = int(
    os.getenv("LOGSTASH_CRITICAL_AFTER_SECONDS", str(20 * 60))
)

GPIB_INDEX_BASE = os.getenv("INGESTOR_INDEX", "scpi_parsed")
GPIB_HEALTH_INDEX_PATTERN = os.getenv(
    "GPIB_HEALTH_INDEX_PATTERN", f"{GPIB_INDEX_BASE}-*"
)
GPIB_WARN_AFTER_SECONDS = int(
    os.getenv("GPIB_WARN_AFTER_SECONDS", str(5 * 24 * 3600))
)
GPIB_CRITICAL_AFTER_SECONDS = int(
    os.getenv("GPIB_CRITICAL_AFTER_SECONDS", str(7 * 24 * 3600))
)


def _default_ftp_dir() -> Path:
    return Path(getattr(settings, "FTP_CLEANUP_DIR", Path.home() / "ftp"))


def _default_completed_log_path() -> Path:
    return Path(
        getattr(
            settings,
            "FTP_COMPLETED_LOG_PATH",
            "/deploy/integrations/winlog/logstash/data/completed-files.log",
        )
    )


def _load_completed_list(log_path: Path) -> list[str]:
    if not log_path.exists():
        logger.warning("Completed log file not found: %s", log_path)
        return []

    try:
        with log_path.open("r", encoding="utf-8") as handle:
            lines = [line.strip() for line in handle if line.strip()]
            logger.info(
                "Loaded %d completed file entry(ies) from %s",
                len(lines),
                log_path,
            )
            return lines
    except OSError as err:
        logger.error("Failed to read %s: %s", log_path, err)
        return []


@shared_task(queue="maintenance")
def run_logrotate() -> dict[str, object]:
    """Run logrotate once for the Parseus webapp log configuration."""
    current_file_path = Path(__file__).resolve()
    cfg_path = current_file_path.parents[2] / "config" / "logrotate.conf"

    cmd = ["logrotate", "-v", str(cfg_path)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)

    if result.returncode != 0:
        logger.error(
            "logrotate failed (rc=%s): %s",
            result.returncode,
            (result.stderr or result.stdout).strip(),
        )
    else:
        logger.info("logrotate completed successfully")

    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": (result.stdout or "").strip(),
        "stderr": (result.stderr or "").strip(),
    }


@shared_task(queue="maintenance")
def cleanup_ftp_files(
    ftp_dir: str | None = None,
    completed_log: str | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    """
    Remove files listed in the Logstash completed-files log from the FTP directory.

    Args:
        ftp_dir: Optional override for the FTP directory.
        completed_log: Optional override for completed-files log path.
        dry_run: If True, only log files that would be deleted.
    """
    ftp_path = Path(ftp_dir) if ftp_dir else _default_ftp_dir()
    completed_log_path = (
        Path(completed_log) if completed_log else _default_completed_log_path()
    )

    logger.info(
        "cleanup_ftp_files starting: ftp_dir=%s completed_log=%s dry_run=%s",
        ftp_path,
        completed_log_path,
        dry_run,
    )

    entries = _load_completed_list(completed_log_path)
    if not entries:
        return {
            "ok": True,
            "dry_run": dry_run,
            "processed_entries": 0,
            "deleted": 0,
            "missing": 0,
            "errors": 0,
        }

    deleted = 0
    missing = 0
    errors = 0

    for entry in entries:
        target_path = ftp_path / Path(entry).name

        if not target_path.exists():
            missing += 1
            logger.warning("File not found, skipping: %s", target_path)
            continue

        if target_path.is_dir():
            errors += 1
            logger.error(
                "Expected file but found directory, skipping: %s", target_path
            )
            continue

        if dry_run:
            logger.info("DRY RUN: would remove %s", target_path)
            continue

        try:
            target_path.unlink()
            deleted += 1
            logger.info("Removed %s", target_path)
        except OSError as err:
            errors += 1
            logger.error("Failed to remove %s: %s", target_path, err)

    summary = {
        "ok": errors == 0,
        "dry_run": dry_run,
        "processed_entries": len(entries),
        "deleted": deleted,
        "missing": missing,
        "errors": errors,
    }
    logger.info("cleanup_ftp_files complete: %s", summary)
    return summary


def _query_latest_timestamp(index_pattern: str) -> datetime | None:
    """Return the latest @timestamp in the index pattern, or None if none found."""
    datastore = get_ds_client()
    body = {
        "query": {"match_all": {}},
        "sort": [{"@timestamp": {"order": "desc"}}],
        "size": 1,
        "_source": ["@timestamp"],
    }

    response = datastore.search(
        index=index_pattern,
        body=body,
        allow_no_indices=True,
        ignore_unavailable=True,
    )

    hits = response.get("hits", {}).get("hits", [])
    if not hits:
        return None

    raw_timestamp = hits[0].get("_source", {}).get("@timestamp")
    if not raw_timestamp:
        return None

    return datetime_parser(raw_timestamp)


def _classify_freshness(
    *,
    latest_event_at: datetime | None,
    warn_after_seconds: int,
    critical_after_seconds: int,
    missing_data_status: str = "critical",
) -> tuple[str, float | None]:
    """Classify freshness based on age in seconds and warning thresholds."""
    if latest_event_at is None:
        return missing_data_status, None

    age_seconds = max(
        0.0,
        (datetime.now(timezone.utc) - latest_event_at).total_seconds(),
    )
    if age_seconds > critical_after_seconds:
        return "critical", age_seconds
    if age_seconds > warn_after_seconds:
        return "warning", age_seconds
    return "ok", age_seconds


def _write_health_status(service: str, payload: dict[str, object]) -> str:
    key = f"{INGESTOR_HEALTH_REDIS_PREFIX}:{service}"
    redis_client.set(key, json.dumps(payload, default=str))
    return key


def _evaluate_ingestor_health(
    *,
    service: str,
    index_pattern: str,
    warn_after_seconds: int,
    critical_after_seconds: int,
    missing_data_status: str,
) -> dict[str, object]:
    now = datetime.now(timezone.utc)

    try:
        latest_event_at = _query_latest_timestamp(index_pattern=index_pattern)
        status, age_seconds = _classify_freshness(
            latest_event_at=latest_event_at,
            warn_after_seconds=warn_after_seconds,
            critical_after_seconds=critical_after_seconds,
            missing_data_status=missing_data_status,
        )
        ok = status in {"ok", "warning"}
        message = (
            "No matching events found"
            if latest_event_at is None
            else f"Latest event is {age_seconds:.0f} second(s) old"
        )

        result: dict[str, object] = {
            "ok": ok,
            "service": service,
            "status": status,
            "index_pattern": index_pattern,
            "checked_at": now.isoformat(),
            "latest_event_at": (
                latest_event_at.astimezone(timezone.utc).isoformat()
                if latest_event_at
                else None
            ),
            "age_seconds": age_seconds,
            "warn_after_seconds": warn_after_seconds,
            "critical_after_seconds": critical_after_seconds,
            "message": message,
        }
    except Exception as err:
        logger.exception("Failed ingestor health check for %s", service)
        result = {
            "ok": False,
            "service": service,
            "status": "error",
            "index_pattern": index_pattern,
            "checked_at": now.isoformat(),
            "latest_event_at": None,
            "age_seconds": None,
            "warn_after_seconds": warn_after_seconds,
            "critical_after_seconds": critical_after_seconds,
            "message": f"health check failed: {err}",
        }

    key = _write_health_status(service=service, payload=result)
    result["redis_key"] = key

    if result["status"] in {"critical", "error"}:
        logger.error("Ingestor health %s: %s", service, result)
    elif result["status"] == "warning":
        logger.warning("Ingestor health %s: %s", service, result)
    else:
        logger.info("Ingestor health %s: %s", service, result)

    return result


@shared_task(queue="maintenance")
def check_logstash_ingestor_health() -> dict[str, object]:
    """Check that logstash-backed ingestion is still reaching Elasticsearch."""
    return _evaluate_ingestor_health(
        service="logstash",
        index_pattern=LOGSTASH_HEALTH_INDEX_PATTERN,
        warn_after_seconds=LOGSTASH_WARN_AFTER_SECONDS,
        critical_after_seconds=LOGSTASH_CRITICAL_AFTER_SECONDS,
        missing_data_status="critical",
    )


@shared_task(queue="maintenance")
def check_gpib_ingestor_health() -> dict[str, object]:
    """Check that gpib ingestion has produced data recently enough for expected cadence."""
    return _evaluate_ingestor_health(
        service="gpib",
        index_pattern=GPIB_HEALTH_INDEX_PATTERN,
        warn_after_seconds=GPIB_WARN_AFTER_SECONDS,
        critical_after_seconds=GPIB_CRITICAL_AFTER_SECONDS,
        missing_data_status="warning",
    )


@shared_task(queue="maintenance")
def check_ingestor_health() -> dict[str, dict[str, object]]:
    """Run all ingestor freshness checks and return combined results."""
    return {
        "logstash": check_logstash_ingestor_health(),
        "gpib": check_gpib_ingestor_health(),
    }
