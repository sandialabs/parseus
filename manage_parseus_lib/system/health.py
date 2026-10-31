from __future__ import annotations

import socket
import ssl
import time
import urllib.error
import urllib.request

from manage_parseus_lib.constants import DEFAULT_HOST
from manage_parseus_lib.output import die, info, ok, warn

def port_is_available(host: str, port: int) -> bool:
    """
    Returns True if no listener is reachable on the given host:port for any
    resolved address family. Returns False if a TCP connection succeeds.
    """
    try:
        infos = socket.getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror:
        # If the host cannot be resolved, skip the availability check for it.
        # Docker Compose validation should catch invalid host bindings.
        return True

    for family, socktype, proto, _, sockaddr in infos:
        s = socket.socket(family, socktype, proto)
        s.settimeout(0.5)
        try:
            rc = s.connect_ex(sockaddr)
            if rc == 0:
                return False
        finally:
            s.close()

    return True

def wait_for_port(
    host: str, port: int, timeout: int = 60, interval: float = 1.0
) -> None:
    info(f"Waiting for {host}:{port} to become available...")
    deadline = time.time() + timeout

    while time.time() < deadline:
        if not port_is_available(host, port):
            ok(f"Port {host}:{port} is now listening")
            return
        time.sleep(interval)

    die(f"Timed out waiting for {host}:{port} to become available")

def wait_for_https_ready(
    url: str,
    timeout: int = 60,
    interval: float = 2.0,
    allow_self_signed: bool = True,
    warn_on_blocked: bool = True,
) -> None:
    info(f"Waiting for application readiness at {url}...")
    deadline = time.time() + timeout

    context = None
    if allow_self_signed:
        context = ssl._create_unverified_context()

    last_err = None

    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5, context=context) as resp:
                status = resp.getcode()
                ok(f"Application responded at {url} (HTTP {status})")
                return

        except urllib.error.HTTPError as e:
            status = getattr(e, "code", None)

            # Server responded, so it's reachable.
            if status is not None:
                if warn_on_blocked and status in (401, 403, 407):
                    warn(
                        f"Application at {url} responded with HTTP {status}. "
                        "This may indicate the application is up but access is being "
                        "blocked by authentication, authorization, or a proxy. "
                        "Continuing installer."
                    )
                    return

                ok(f"Application responded at {url} (HTTP {status})")
                return

            last_err = str(e)

        except urllib.error.URLError as e:
            last_err = str(e.reason) if hasattr(e, "reason") else str(e)

            if warn_on_blocked:
                msg = last_err.lower()
                proxy_indicators = (
                    "proxy",
                    "tunnel connection failed",
                    "forbidden",
                    "certificate",
                )
                if any(indicator in msg for indicator in proxy_indicators):
                    warn(
                        f"Request to {url} may be blocked by a proxy/security layer "
                        f"({last_err}). The application may still be available in a browser. "
                        "Continuing installer."
                    )
                    return

        except Exception as e:
            last_err = str(e)

        time.sleep(interval)

    die(f"Timed out waiting for application readiness at {url}\nLast error: {last_err}")

def default_health_host_for_bind(bind_host: str) -> str:
    if bind_host in {"0.0.0.0", "::"}:
        return DEFAULT_HOST
    return bind_host

def build_default_public_url(host: str, port: int) -> str:
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port_part = "" if port == 443 else f":{port}"
    return f"https://{host}{port_part}/"

