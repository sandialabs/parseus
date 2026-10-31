from __future__ import annotations

import os
import re
import selectors
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import List, Optional

from manage_parseus_lib.output import info

@dataclass
class CmdResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    rc: int = 0

def coerce_command_output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace").strip()
    return str(value).strip()

def run(cmd: List[str], timeout: Optional[int] = None) -> CmdResult:
    try:
        p = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
        return CmdResult(
            ok=(p.returncode == 0),
            stdout=p.stdout.strip(),
            stderr=p.stderr.strip(),
            rc=p.returncode,
        )
    except subprocess.TimeoutExpired as e:
        stdout = coerce_command_output(e.stdout)
        stderr = (
            coerce_command_output(e.stderr) or f"Command timed out after {timeout}s"
        )
        return CmdResult(ok=False, stdout=stdout, stderr=stderr, rc=124)
    except FileNotFoundError:
        return CmdResult(ok=False, stderr=f"Command not found: {cmd[0]}", rc=127)

def clean_status_text(value: str) -> str:
    value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)
    value = value.replace("\r", " ").replace("\n", " ")
    value = " ".join(value.split())
    return value.strip()

def print_status_line(value: str) -> None:
    prefix = "[INFO] "
    width = max(shutil.get_terminal_size((100, 20)).columns, len(prefix) + 20)
    available = max(width - len(prefix) - 1, 20)
    value = clean_status_text(value)

    if len(value) > available:
        value = "…" + value[-(available - 1) :]

    sys.stdout.write("\r\033[K" + prefix + value)
    sys.stdout.flush()

def clear_status_line() -> None:
    sys.stdout.write("\r\033[K")
    sys.stdout.flush()

def run_streaming(
    cmd: List[str],
    timeout: Optional[int] = None,
    heartbeat_interval: int = 30,
    heartbeat_message: str = "Command is still running",
) -> CmdResult:
    """
    Run a long command while showing a single updating status line.

    Docker build/pull/load commands can run for several minutes. Capturing their
    output until completion makes the installer look stuck, while dumping all of
    it can be noisy. This helper captures recent output for errors but displays
    only the latest useful status message in-place.
    """
    info(f"Running: {' '.join(cmd)}")

    try:
        p = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
    except FileNotFoundError:
        return CmdResult(ok=False, stderr=f"Command not found: {cmd[0]}", rc=127)

    assert p.stdout is not None

    start = time.monotonic()
    last_output = start
    last_status = heartbeat_message
    pending = ""
    tail = bytearray()
    max_tail = 64 * 1024
    use_status_line = sys.stdout.isatty()

    sel = selectors.DefaultSelector()
    sel.register(p.stdout, selectors.EVENT_READ)

    if use_status_line:
        print_status_line(heartbeat_message)

    try:
        while True:
            now = time.monotonic()
            if timeout is not None and now - start >= timeout:
                p.kill()
                p.wait()
                message = f"Command timed out after {timeout}s"
                if use_status_line:
                    clear_status_line()
                print(f"[WARN] {message}", file=sys.stderr)
                return CmdResult(
                    ok=False,
                    stdout=tail.decode(errors="replace").strip(),
                    stderr=message,
                    rc=124,
                )

            events = sel.select(timeout=1.0)
            if events:
                for key, _ in events:
                    chunk = os.read(key.fileobj.fileno(), 4096)
                    if not chunk:
                        sel.unregister(key.fileobj)
                        continue

                    tail.extend(chunk)
                    if len(tail) > max_tail:
                        del tail[: len(tail) - max_tail]

                    pending += chunk.decode(errors="replace")
                    parts = re.split(r"[\r\n]+", pending)
                    if pending.endswith(("\r", "\n")):
                        candidates = parts[:-1]
                        pending = ""
                    else:
                        candidates = parts[:-1]
                        pending = parts[-1]

                    if len(pending) > 4096:
                        pending = pending[-4096:]

                    if pending.strip():
                        candidates.append(pending)

                    for candidate in candidates:
                        candidate = clean_status_text(candidate)
                        if candidate:
                            last_status = candidate

                    last_output = time.monotonic()
                    if use_status_line:
                        print_status_line(last_status)
            elif heartbeat_interval > 0 and now - last_output >= heartbeat_interval:
                elapsed = int(now - start)
                status = f"{heartbeat_message} ({elapsed}s elapsed)"
                if last_status and last_status != heartbeat_message:
                    status = f"{status}; latest: {last_status}"

                if use_status_line:
                    print_status_line(status)
                else:
                    info(status)
                last_output = now

            if p.poll() is not None and not sel.get_map():
                break
    finally:
        sel.close()
        p.stdout.close()
        if use_status_line:
            clear_status_line()

    output_tail = tail.decode(errors="replace").strip()
    return CmdResult(
        ok=(p.returncode == 0),
        stdout=output_tail,
        stderr="" if p.returncode == 0 else output_tail,
        rc=p.returncode or 0,
    )

