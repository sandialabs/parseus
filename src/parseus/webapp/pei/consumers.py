import asyncio
import json
import os
from pathlib import Path

from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings


POLL_INTERVAL_SECONDS = 0.25
LOG_FILE_WAIT_ATTEMPTS = 120  # 30 seconds before showing a waiting message


class PeatLogConsumer(AsyncWebsocketConsumer):
    """Stream PEAT console output to the webapp in near realtime."""

    async def connect(self):
        await self.accept()
        self.file_path = None
        self.file_offset = 0
        self.parent_run_dir = None
        self.run_dir = None
        self.keep_streaming = True

    async def receive(self, text_data):
        """Handle incoming messages from the WebSocket client."""
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send_error("Invalid log stream request.")
            return

        run_method = data.get("run_method")
        if run_method == "pull":
            self.parent_run_dir = settings.PEAT_PULL_DIR
        elif run_method == "scan":
            self.parent_run_dir = settings.PEAT_SCAN_DIR
        else:
            await self.send_error("Unknown PEAT run method.")
            return

        self.run_dir = data.get("run_dir")
        if not self.run_dir:
            await self.send_error("Run directory is not available.")
            return

        if not self.set_file_path():
            await self.send_error("Invalid run directory.")
            return

        if await self.send_existing_log_content():
            await self.stream_log_lines()

    def set_file_path(self):
        """Resolve the current log path, preferring subprocess console output."""
        if not self.parent_run_dir or not self.run_dir:
            return False

        parent = Path(self.parent_run_dir).resolve()
        log_dir = (parent / self.run_dir / "logs").resolve()
        try:
            log_dir.relative_to(parent)
        except ValueError:
            return False

        console_log = log_dir / "console.log"
        peat_log = log_dir / "peat.log"
        self.file_path = console_log if console_log.exists() else peat_log
        return True

    async def send_existing_log_content(self):
        """Send existing log content, waiting briefly for PEAT to create it."""
        for _ in range(LOG_FILE_WAIT_ATTEMPTS):
            self.set_file_path()
            if self.file_path and os.path.exists(self.file_path):
                with open(self.file_path, encoding="utf-8", errors="replace") as f:
                    content = f.read()
                    self.file_offset = f.tell()
                await self.send(
                    json.dumps({"type": "existing_log", "content": content})
                )
                return True
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

        await self.send_status("Log file not found yet; waiting for PEAT output...")
        return True

    async def stream_log_lines(self):
        """Stream new lines from the selected log file."""
        while self.keep_streaming:
            self.set_file_path()
            if self.file_path and os.path.exists(self.file_path):
                break
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        else:
            return

        with open(self.file_path, encoding="utf-8", errors="replace") as f:
            f.seek(self.file_offset)
            while self.keep_streaming:
                lines = self.read_lines(f, 25)
                if lines:
                    await self.send(
                        json.dumps({"type": "new_lines", "content": "".join(lines)})
                    )
                else:
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)

    def read_lines(self, file, num_lines):
        """Read a specified number of lines from the log file."""
        lines = []
        for _ in range(num_lines):
            line = file.readline()
            if not line:
                break
            lines.append(line)
        return lines

    async def send_status(self, message):
        await self.send(
            json.dumps({"type": "status", "message": message, "content": ""})
        )

    async def send_error(self, message):
        await self.send(
            json.dumps({"type": "error", "message": message, "content": ""})
        )

    async def disconnect(self, close_code):
        self.keep_streaming = False
