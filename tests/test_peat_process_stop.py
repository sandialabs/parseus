import sys
import threading
from pathlib import Path

from parseus.webapp.pei import models as pei_models
from parseus.webapp.pei import peat_process


def test_run_peat_subprocess_terminates_when_stop_requested(tmp_path: Path):
    stop = threading.Event()
    started = threading.Event()

    def on_start(pid):
        started.set()
        # Simulate another container flipping the run to "stopped".
        threading.Timer(0.3, stop.set).start()

    command = [sys.executable, "-c", "import time; time.sleep(60)"]
    returncode = peat_process.run_peat_subprocess(
        command,
        tmp_path,
        on_start=on_start,
        should_stop=stop.is_set,
        stop_poll_seconds=0.1,
    )

    assert started.is_set()
    assert returncode != 0
    assert "return code" in (tmp_path / "logs" / "console.log").read_text()


def test_current_process_host_is_stable_uuid():
    import uuid

    peat_process.current_process_host.cache_clear()
    first = peat_process.current_process_host()
    assert first == peat_process.current_process_host()
    uuid.UUID(first)


def test_current_process_host_differs_per_pid_namespace(monkeypatch):
    def fake_readlink_factory(value):
        return lambda path: value

    peat_process.current_process_host.cache_clear()
    monkeypatch.setattr(peat_process.os, "readlink", fake_readlink_factory("pid:[1]"))
    host_a = peat_process.current_process_host()
    peat_process.current_process_host.cache_clear()
    monkeypatch.setattr(peat_process.os, "readlink", fake_readlink_factory("pid:[2]"))
    host_b = peat_process.current_process_host()
    peat_process.current_process_host.cache_clear()

    assert host_a != host_b


def test_current_process_host_falls_back_to_random_uuid(monkeypatch):
    def broken_readlink(path):
        raise OSError("no /proc")

    peat_process.current_process_host.cache_clear()
    monkeypatch.setattr(peat_process.os, "readlink", broken_readlink)
    host_a = peat_process.current_process_host()
    peat_process.current_process_host.cache_clear()
    host_b = peat_process.current_process_host()
    peat_process.current_process_host.cache_clear()

    # Never matches another process, so stop() delegates to the owner.
    assert host_a != host_b


def test_stop_does_not_signal_pid_from_other_host(monkeypatch):
    killed = []
    monkeypatch.setattr(
        pei_models, "terminate_process_group", lambda pid: killed.append(pid)
    )
    monkeypatch.setattr(pei_models, "current_process_host", lambda: "web")

    class FakeRun:
        status = "running"
        task_id = None
        process_id = 1234
        process_host = "worker"
        run_dir = None
        saved = []

        def refresh_from_db(self, fields=None):
            pass

        def save(self, update_fields=None):
            self.saved.append(update_fields)

        def _append_console_message(self, message):
            pass

        def get_method(self):
            return "scan"

    run = FakeRun()
    pei_models.PeatRun.stop(run)

    assert killed == []
    assert run.process_id == 1234
    assert ["process_id", "process_host"] not in run.saved
