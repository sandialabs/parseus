import atexit
import json
import os
import signal
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import blake2b
from os import environ
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any

from parseus.ingestors.gpib.logger import setup_logger
from parseus.datastore.client import get_datastore


@dataclass(frozen=True)
class Settings:
    datastore_host_url: str
    datastore_type: str
    datastore_auth: str | None
    index_base: str
    gpib_host: str
    gpib_port: int
    socket_timeout_seconds: float
    reconnect_delay_base_seconds: float
    reconnect_delay_max_seconds: float
    recv_buffer_size: int
    max_events_per_flush: int
    idle_flush_seconds: float
    flush_check_interval_seconds: float
    capture_dir: Path
    log_file: Path


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    value = int(environ.get(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _float_env(name: str, default: float, minimum: float = 0.0) -> float:
    value = float(environ.get(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def load_settings() -> Settings:
    """Load and validate GPIB ingestor settings from the environment."""
    default_artifacts_dir = Path.home() / ".parseus" / "artifacts"
    capture_dir = Path(
        environ.get("INGESTOR_CAPTURE_DIR", str(default_artifacts_dir / "pcaps"))
    )
    log_file = Path(
        environ.get(
            "INGESTOR_LOG_FILE",
            str(default_artifacts_dir / "logs" / "gpib_parser.log"),
        )
    )
    reconnect_delay_base = _float_env("INGESTOR_GPIB_RECONNECT_DELAY_BASE", 1.0, 0.1)
    reconnect_delay_max = _float_env("INGESTOR_GPIB_RECONNECT_DELAY_MAX", 30.0, 0.1)
    if reconnect_delay_base > reconnect_delay_max:
        raise ValueError(
            "INGESTOR_GPIB_RECONNECT_DELAY_BASE must be <= "
            "INGESTOR_GPIB_RECONNECT_DELAY_MAX"
        )

    return Settings(
        datastore_host_url=environ.get("DATASTORE_HOST_URL", "http://localhost:9202"),
        datastore_type=environ.get("DATASTORE_TYPE", "elasticsearch"),
        datastore_auth=environ.get("DATASTORE_AUTH"),
        index_base=environ.get("INGESTOR_INDEX", "scpi_parsed"),
        gpib_host=environ.get("INGESTOR_GPIB_IP", "localhost"),
        gpib_port=_int_env("INGESTOR_GPIB_PORT", 1234),
        socket_timeout_seconds=_float_env("INGESTOR_GPIB_SOCKET_TIMEOUT", 30.0, 0.1),
        reconnect_delay_base_seconds=reconnect_delay_base,
        reconnect_delay_max_seconds=reconnect_delay_max,
        recv_buffer_size=_int_env("INGESTOR_RECV_BUFFER_SIZE", 6000),
        max_events_per_flush=_int_env("INGESTOR_MAX_EVENTS_PER_FLUSH", 1000),
        idle_flush_seconds=_float_env("INGESTOR_IDLE_FLUSH_SECONDS", 60.0, 0.1),
        flush_check_interval_seconds=_float_env("INGESTOR_FLUSH_CHECK_INTERVAL", 5.0, 0.1),
        capture_dir=capture_dir,
        log_file=log_file,
    )


SETTINGS = load_settings()
DATASTORE = get_datastore(
    datastore_host_url=SETTINGS.datastore_host_url,
    datastore_type=SETTINGS.datastore_type,
    datastore_auth=SETTINGS.datastore_auth,
)

logger = setup_logger("gpib_parser", SETTINGS.log_file)

_event_lock = Lock()
_counter_lock = Lock()
_shutdown = Event()
EVENT_BUFFER: list[dict[str, Any]] = []
LAST_EVENT_TIME: float | None = None
LAST_EVENT_HASH: str | None = None


def main() -> None:
    """Run combined listener+parser loop over TCP payloads from the GPIB bridge."""
    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)

    flusher = Thread(target=idle_flush_loop, daemon=True)
    flusher.start()

    atexit.register(flush_events, "process exit")

    delay = SETTINGS.reconnect_delay_base_seconds
    while not _shutdown.is_set():
        sock = None
        try:
            sock = make_socket()
            delay = SETTINGS.reconnect_delay_base_seconds
            receive_and_process_loop(sock)
        except (socket.error, RuntimeError) as exc:
            if not _shutdown.is_set():
                logger.error("Connection lost: %s", exc)
        except Exception:
            logger.exception("Unexpected error in main loop")
        finally:
            close_socket(sock)

        if _shutdown.is_set():
            break

        logger.info("Reconnecting in %.1f second(s)", delay)
        _shutdown.wait(delay)
        delay = min(delay * 2, SETTINGS.reconnect_delay_max_seconds)

    flush_events("shutdown")


def request_shutdown(signum: int, _frame: object) -> None:
    logger.info("Received signal %s; shutting down", signum)
    _shutdown.set()


def make_socket() -> socket.socket:
    logger.info("Connecting to %s:%s", SETTINGS.gpib_host, SETTINGS.gpib_port)
    sock = socket.create_connection(
        (SETTINGS.gpib_host, SETTINGS.gpib_port),
        timeout=SETTINGS.socket_timeout_seconds,
    )
    sock.settimeout(SETTINGS.socket_timeout_seconds)
    return sock


def close_socket(sock: socket.socket | None) -> None:
    if sock is None:
        return
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except Exception:
        pass
    try:
        sock.close()
    except Exception:
        pass


def receive_and_process_loop(sock: socket.socket) -> None:
    while not _shutdown.is_set():
        try:
            payload = sock.recv(SETTINGS.recv_buffer_size)
        except socket.timeout:
            logger.warning("Socket receive timed out")
            raise RuntimeError("socket receive timeout")

        if not payload:
            logger.warning("Remote closed the connection")
            raise RuntimeError("socket connection broken")

        process_payload(payload, sock)


def process_payload(payload: bytes, sock: socket.socket) -> None:
    global LAST_EVENT_HASH, LAST_EVENT_TIME

    event_hash = blake2b(payload, digest_size=16).hexdigest()
    if event_hash == LAST_EVENT_HASH:
        logger.debug("Skipping consecutive duplicate payload (%d bytes)", len(payload))
        return

    decoded_data = payload.decode("utf-8", errors="ignore").rstrip("\x00\r\n")
    if not decoded_data:
        return

    remote_ip, remote_port = sock.getpeername()
    local_ip, local_port = sock.getsockname()
    now = datetime.now(timezone.utc)

    doc = {
        "@timestamp": now,
        "ip": {
            "source": remote_ip,
            "destination": local_ip,
        },
        "tcp": {
            "src_port": remote_port,
            "dst_port": local_port,
        },
        "source": "GPIB_SOCKET",
        "data": decoded_data,
        "payload_bytes": len(payload),
    }

    try:
        push_to_datastore(doc=doc, datastore=DATASTORE, index_base=SETTINGS.index_base)
    except Exception:
        logger.exception("Failed to push parsed doc to datastore")

    event = {
        "timestamp": now.isoformat(),
        "source_ip": remote_ip,
        "source_port": remote_port,
        "destination_ip": local_ip,
        "destination_port": local_port,
        "payload_bytes": len(payload),
        "data": decoded_data,
    }

    with _event_lock:
        EVENT_BUFFER.append(event)
        LAST_EVENT_TIME = time.time()
        should_flush = len(EVENT_BUFFER) >= SETTINGS.max_events_per_flush

    LAST_EVENT_HASH = event_hash

    if should_flush:
        flush_events("max event count reached")


def push_to_datastore(doc: dict[str, Any], datastore: Any, index_base: str) -> None:
    current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    index = f"{index_base}-{current_date}"
    logger.debug("index name: %s", index)
    resp = datastore.index(index=index, document=doc)
    logger.info("Pushed to datastore with result: %s", resp.get("result"))


def idle_flush_loop() -> None:
    logger.debug("idle_flush_loop is running")
    while not _shutdown.is_set():
        try:
            _shutdown.wait(SETTINGS.flush_check_interval_seconds)
            with _event_lock:
                event_count = len(EVENT_BUFFER)
                last_event_time = LAST_EVENT_TIME

            if event_count == 0 or last_event_time is None:
                continue

            idle_time = time.time() - last_event_time
            if idle_time >= SETTINGS.idle_flush_seconds:
                flush_events(f"idle for {idle_time:.1f} seconds")
        except Exception:
            logger.exception("Exception in idle_flush_loop")


def flush_events(reason: str = "unspecified") -> None:
    with _event_lock:
        if not EVENT_BUFFER:
            return
        events_to_write = EVENT_BUFFER[:]
        EVENT_BUFFER.clear()

    filename = write_events_to_file(events_to_write)
    logger.info(
        "Flushed %d event(s) to %s (reason: %s)",
        len(events_to_write),
        filename,
        reason,
    )


def write_events_to_file(event_list: list[dict[str, Any]]) -> Path:
    today = datetime.now(timezone.utc)
    date_dir = SETTINGS.capture_dir / f"{today:%Y/%m/%d}"
    date_dir.mkdir(parents=True, exist_ok=True)

    counter_file = date_dir / ".counter"
    next_id = _next_counter(counter_file)

    filename = date_dir / f"capture_{next_id}.ndjson"
    temp_filename = filename.with_name(f".{filename.name}.{os.getpid()}.tmp")
    with temp_filename.open("w", encoding="utf-8") as handle:
        for event in event_list:
            handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())

    temp_filename.replace(filename)
    logger.info("Wrote %d event(s) to %s", len(event_list), filename)
    return filename


def _next_counter(counter_path: Path) -> int:
    with _counter_lock:
        if counter_path.is_file():
            with counter_path.open("r+", encoding="utf-8") as handle:
                content = handle.read().strip()
                last = int(content) if content else 0
                nxt = last + 1
                handle.seek(0)
                handle.write(str(nxt))
                handle.truncate()
        else:
            nxt = 1
            counter_path.parent.mkdir(parents=True, exist_ok=True)
            with counter_path.open("w", encoding="utf-8") as handle:
                handle.write(str(nxt))
    return nxt


if __name__ == "__main__":
    main()
