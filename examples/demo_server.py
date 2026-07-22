#!/usr/bin/env python3
"""Minimal demo server that accepts LogBalloon MVP endpoints."""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8765
LOG_PATH = Path(__file__).resolve().parent / "received.jsonl"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        sys.stdout.write("[server] " + (fmt % args) + "\n")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def _ok(self) -> None:
        body = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in {"/startup", "/event", "/crash"}:
            self.send_error(404, "Not Found")
            return
        payload = self._read_json()
        record = {"path": self.path, "body": payload}
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"[server] {self.path}: {json.dumps(payload, ensure_ascii=False)}")
        self._ok()


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"LogBalloon demo server on http://{HOST}:{PORT}")
    print(f"Appending received payloads to {LOG_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down")
        server.server_close()


if __name__ == "__main__":
    main()
