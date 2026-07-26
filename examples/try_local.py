#!/usr/bin/env python3
"""One-command local check: receiver + client in a single process.

    python examples/try_local.py
    python examples/try_local.py --crash    # also report an uncaught error

Starts a throwaway HTTP receiver on a free port, sends startup / event
through LogBalloon, then prints exactly what the server received.
No configuration, no second terminal.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

# Allow running straight from a clone: python examples/try_local.py
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from logballoon import LogBalloon  # noqa: E402

API_KEY = "demo-key"


def start_receiver() -> tuple[ThreadingHTTPServer, list[dict]]:
    """Throwaway receiver that requires Authorization: Bearer <API_KEY>."""
    received: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def do_POST(self) -> None:  # noqa: N802
            if self.headers.get("Authorization") != f"Bearer {API_KEY}":
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b'{"ok":false}')
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            received.append({"path": self.path, "body": body})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, received


def main() -> None:
    parser = argparse.ArgumentParser(description="LogBalloon local smoke test")
    parser.add_argument(
        "--crash",
        action="store_true",
        help="Also raise an uncaught error so /crash is delivered",
    )
    args = parser.parse_args()

    server, received = start_receiver()
    host, port = server.server_address
    endpoint = f"http://{host}:{port}"
    print(f"receiver listening on {endpoint} (api key required)\n")

    # TemporaryDirectory keeps this demo away from your real app data.
    with TemporaryDirectory() as tmp:
        lb = LogBalloon(
            app_name="Try LogBalloon",
            version="0.0.1",
            endpoint=endpoint,
            api_key=API_KEY,
            data_root=tmp,
            flush_interval=1.0,
        )
        lb.start()
        lb.event("export_complete", {"rows": 120, "format": "csv"})

        if args.crash:
            print("(the traceback below is intentional)\n")
            try:
                raise ValueError("intentional demo crash")
            except ValueError:
                # sys.excepthook is LogBalloon's while the client is running.
                sys.excepthook(*sys.exc_info())

        lb.flush(timeout=5.0)
        print(f"queue pending after flush: {lb.pending()}\n")
        lb.stop()

    for item in received:
        print(f"--- {item['path']}")
        print(json.dumps(item["body"], ensure_ascii=False, indent=2))

    server.shutdown()

    paths = [item["path"] for item in received]
    print("\nreceived:", ", ".join(paths) if paths else "(nothing)")
    print("Offline behaviour: with no server reachable, the same calls queue instead.")


if __name__ == "__main__":
    main()
