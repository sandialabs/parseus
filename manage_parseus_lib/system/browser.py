from __future__ import annotations

import os
import shutil
import subprocess
from typing import Tuple

from manage_parseus_lib.output import info

def browser_open_support() -> Tuple[bool, str]:
    """
    Returns (supported, reason). supported=True means it is reasonable to offer
    automatic browser opening on this system.
    """
    if shutil.which("xdg-open") is None:
        return False, "`xdg-open` not found in PATH"

    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        return False, "No graphical display session detected"

    return True, ""

def maybe_open_browser(url: str, open_browser_requested: bool) -> None:
    print(f"\nParseus is available at: {url}")

    if not open_browser_requested:
        return

    supported, reason = browser_open_support()
    if not supported:
        info(f"Automatic browser launch unavailable: {reason}")
        info(f"Please open this URL manually: {url}")
        return

    open_browser(url)

def open_browser(url: str) -> None:
    supported, reason = browser_open_support()
    if not supported:
        info(f"Cannot automatically open browser: {reason}")
        info(f"Please open this URL manually: {url}")
        return

    info(f"Opening browser to {url}...")
    try:
        p = subprocess.Popen(
            ["xdg-open", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
        info(f"Browser launch command started (pid={p.pid})")
        info(f"If no browser appears, open this URL manually: {url}")
    except Exception as e:
        info(f"Could not automatically open browser: {e}")
        info(f"Please open this URL manually: {url}")

