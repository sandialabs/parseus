"""Configure a Prologix GPIB-ETHERNET bridge for listener-only ingestion."""

import argparse
import socket

DEFAULT_TIMEOUT_SECONDS = 10.0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Configure a Prologix GPIB-ETHERNET bridge for listener-only mode."
    )
    parser.add_argument(
        "--host", required=True, type=str, help="Bridge IP address or DNS name"
    )
    parser.add_argument("--port", default=1234, type=int, help="Bridge TCP port")
    parser.add_argument(
        "--timeout",
        default=DEFAULT_TIMEOUT_SECONDS,
        type=float,
        help="Socket timeout in seconds",
    )
    args = parser.parse_args()
    connect_and_config(args.host, args.port, args.timeout)


def connect_and_config(host: str, port: int, timeout: float) -> None:
    """Connect to the bridge and send listener-only configuration commands."""
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        send_command(sock, "++auto 0")
        send_command(sock, "++mode 0")
        print("Mode info: " + query(sock, "++read eoi"))
        send_command(sock, "++lon 1")
        print("Listener-only mode enabled.")


def send_command(sock: socket.socket, command: str) -> None:
    sock.sendall(f"{command}\n".encode("ascii"))


def query(sock: socket.socket, command: str) -> str:
    send_command(sock, command)
    data = sock.recv(1024)
    return data.decode("ascii", errors="replace").strip()


if __name__ == "__main__":
    main()
