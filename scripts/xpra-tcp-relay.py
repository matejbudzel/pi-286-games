#!/usr/bin/env python3
"""Small TCP relay used to expose an LXC-local Xpra server through Tailscale."""
import argparse
import select
import socket
import threading


def pump(client, target):
    try:
        with client, socket.create_connection(target, timeout=10) as upstream:
            client.setblocking(False)
            upstream.setblocking(False)
            peers = {client: upstream, upstream: client}
            while peers:
                readable, _, _ = select.select(list(peers), [], [])
                for source in readable:
                    data = source.recv(65536)
                    destination = peers[source]
                    if not data:
                        peers.pop(source, None)
                        peers.pop(destination, None)
                        destination.shutdown(socket.SHUT_WR)
                    else:
                        destination.sendall(data)
    except OSError:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=14500)
    parser.add_argument("--target-host", required=True)
    parser.add_argument("--target-port", type=int, default=14500)
    args = parser.parse_args()
    with socket.create_server((args.listen_host, args.listen_port), reuse_port=False) as listener:
        while True:
            client, _ = listener.accept()
            threading.Thread(target=pump, args=(client, (args.target_host, args.target_port)), daemon=True).start()


if __name__ == "__main__":
    main()
