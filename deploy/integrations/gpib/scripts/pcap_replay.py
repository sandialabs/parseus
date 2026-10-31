"""Replay TCP payloads from a PCAP to exercise the GPIB ingestor locally."""

import argparse
import socket
import time
from pathlib import Path

from scapy.all import Raw, rdpcap


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Serve TCP payloads from a PCAP to a connecting GPIB parser."
    )
    parser.add_argument("-f", "--file", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1", type=str)
    parser.add_argument("-p", "--port", default=1234, type=int)
    parser.add_argument("--delay", default=1.0, type=float, help="Delay between payloads")
    args = parser.parse_args()
    connect_and_send(args.file, args.host, args.port, args.delay)


def connect_and_send(pcap_file: Path, host: str, port: int, delay: float) -> None:
    """Accept one connection and send all Raw packet payloads from a PCAP file."""
    if not pcap_file.is_file():
        raise FileNotFoundError(f"PCAP file not found: {pcap_file}")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_address = (host, port)
        server_socket.bind(server_address)
        server_socket.listen(1)
        print(f"Listening for connections on {server_address[0]}:{server_address[1]}...")
        connection, client_address = server_socket.accept()
        with connection:
            print(f"Connection from {client_address}")
            send_packets(connection, pcap_file, delay)


def send_packets(connection: socket.socket, pcap_file: Path, delay: float) -> None:
    """Send Raw payloads from a PCAP file over an accepted TCP connection."""
    packets = rdpcap(str(pcap_file))
    sent = 0
    for packet in packets:
        if Raw not in packet:
            print(f"Skipping packet with no payload: {packet.summary()}")
            continue

        payload = bytes(packet[Raw])
        connection.sendall(payload)
        sent += 1
        time.sleep(delay)

    print(f"Sent {sent} payload(s) from {pcap_file}")


if __name__ == "__main__":
    main()
