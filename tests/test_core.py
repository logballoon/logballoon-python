from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from logballoon import LogBalloon
from logballoon.queue import OfflineQueue
from logballoon.transport import Transport, TransportError


def test_queue_roundtrip(tmp_path: Path) -> None:
    q = OfflineQueue(tmp_path / "q.sqlite3")
    item_id = q.enqueue("event", {"event": "hello"})
    assert item_id >= 1
    assert q.count() == 1
    items = q.peek()
    assert items[0]["kind"] == "event"
    assert items[0]["payload"]["event"] == "hello"
    q.delete(items[0]["id"])
    assert q.count() == 0


def test_transport_posts_json() -> None:
    received: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            received.append({"path": self.path, "body": body})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        t = Transport(f"http://{host}:{port}", timeout=2.0)
        t.send("startup", {"app": "t"})
        assert received[0]["path"] == "/startup"
        assert received[0]["body"]["app"] == "t"
    finally:
        server.shutdown()


def test_offline_then_online(tmp_path: Path) -> None:
    received: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            received.append({"path": self.path, "body": body})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

    # Offline: bad endpoint → queue retains items
    lb = LogBalloon(
        app_name="TestApp",
        version="0.0.1",
        endpoint="http://127.0.0.1:1",
        data_root=str(tmp_path / "lb"),
        install_excepthook=False,
        flush_interval=60.0,
    )
    lb.start()
    lb.event("offline_event", {"n": 1})
    assert lb.flush(timeout=1.0) == 0
    assert lb.pending() >= 2  # startup + event
    lb.stop(flush=False)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        lb2 = LogBalloon(
            app_name="TestApp",
            version="0.0.1",
            endpoint=f"http://{host}:{port}",
            data_root=str(tmp_path / "lb"),
            install_excepthook=False,
            flush_interval=60.0,
        )
        # Same data root → same queue; do not call start() (would add another startup)
        delivered = lb2.flush(timeout=3.0)
        assert delivered >= 2
        assert lb2.pending() == 0
        paths = {item["path"] for item in received}
        assert "/startup" in paths
        assert "/event" in paths
    finally:
        server.shutdown()


def test_transport_error_on_down() -> None:
    t = Transport("http://127.0.0.1:1", timeout=0.5)
    try:
        t.send("event", {"event": "x"})
        assert False, "expected TransportError"
    except TransportError:
        pass
