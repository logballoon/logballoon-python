#!/usr/bin/env python3
"""Minimal demo server that accepts LogBalloon MVP endpoints."""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8765
LOG_PATH = Path(__file__).resolve().parent / "received.jsonl"

# Set by main() before serving. None = auth disabled (default).
REQUIRED_API_KEY: str | None = None


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

    def _unauthorized(self) -> None:
        body = b'{"ok":false,"error":"unauthorized"}'
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if not REQUIRED_API_KEY:
            return True
        auth = self.headers.get("Authorization", "")
        if auth == f"Bearer {REQUIRED_API_KEY}":
            return True
        if self.headers.get("X-API-Key") == REQUIRED_API_KEY:
            return True
        return False

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in {"/startup", "/event", "/crash", "/user"}:
            self.send_error(404, "Not Found")
            return
        if not self._authorized():
            self._unauthorized()
            return
        payload = self._read_json()
        record = {"path": self.path, "body": payload}
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"[server] {self.path}: {json.dumps(payload, ensure_ascii=False)}")
        self._ok()


def main() -> None:
    global REQUIRED_API_KEY
    parser = argparse.ArgumentParser(description="LogBalloon demo server")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument(
        "--api-key",
        default=os.environ.get("LOGBALLOON_API_KEY"),
        help="Optional shared secret (also: LOGBALLOON_API_KEY). Off by default.",
    )
    args = parser.parse_args()
    REQUIRED_API_KEY = args.api_key or None

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"LogBalloon demo server on http://{args.host}:{args.port}")
    if REQUIRED_API_KEY:
        print("API key auth enabled (Bearer / X-API-Key)")
    else:
        print("API key auth disabled")
    print(f"Appending received payloads to {LOG_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down")
        server.server_close()


if __name__ == "__main__":
    main()
