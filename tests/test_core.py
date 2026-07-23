"""Core SDK tests — keep them small and easy to read."""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from logballoon import LogBalloon
from logballoon.identity import get_or_create_installation_id
from logballoon.queue import OfflineQueue
from logballoon.transport import Transport, TransportError


def _start_server() -> tuple[ThreadingHTTPServer, list[dict], threading.Thread]:
    """Tiny local HTTP server that records POSTs."""
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
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, received, thread


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
    server, received, _ = _start_server()
    host, port = server.server_address
    try:
        t = Transport(f"http://{host}:{port}", timeout=2.0)
        t.send("startup", {"app": "t"})
        assert received[0]["path"] == "/startup"
        assert received[0]["body"]["app"] == "t"
    finally:
        server.shutdown()


def test_transport_error_on_down() -> None:
    t = Transport("http://127.0.0.1:1", timeout=0.5)
    try:
        t.send("event", {"event": "x"})
        raise AssertionError("expected TransportError")
    except TransportError:
        pass


def test_installation_id_persists(tmp_path: Path) -> None:
    first = get_or_create_installation_id(tmp_path)
    second = get_or_create_installation_id(tmp_path)
    assert first == second
    assert len(first) > 10


def test_event_payload_is_free_form(tmp_path: Path) -> None:
    """Envelope is fixed; payload dict is for the app author."""
    server, received, _ = _start_server()
    host, port = server.server_address
    try:
        lb = LogBalloon(
            app_name="TestApp",
            version="0.0.1",
            endpoint=f"http://{host}:{port}",
            data_root=tmp_path / "lb",
            install_excepthook=False,
            flush_interval=60.0,
        )
        lb.start()
        lb.event("export_complete", {"rows": 120, "format": "csv"})
        lb.flush(timeout=3.0)
        assert lb.pending() == 0

        events = [r for r in received if r["path"] == "/event"]
        assert len(events) == 1
        body = events[0]["body"]
        assert body["event"] == "export_complete"
        assert body["payload"] == {"rows": 120, "format": "csv"}
        assert "installation_id" in body
        lb.stop()
    finally:
        server.shutdown()


def test_offline_then_online(tmp_path: Path) -> None:
    lb = LogBalloon(
        app_name="TestApp",
        version="0.0.1",
        endpoint="http://127.0.0.1:1",
        data_root=tmp_path / "lb",
        install_excepthook=False,
        flush_interval=60.0,
    )
    lb.start()
    lb.event("offline_event", {"n": 1})
    assert lb.flush(timeout=1.0) == 0
    assert lb.pending() >= 2
    lb.stop(flush=False)

    server, received, _ = _start_server()
    host, port = server.server_address
    try:
        lb2 = LogBalloon(
            app_name="TestApp",
            version="0.0.1",
            endpoint=f"http://{host}:{port}",
            data_root=tmp_path / "lb",
            install_excepthook=False,
            flush_interval=60.0,
        )
        delivered = lb2.flush(timeout=3.0)
        assert delivered >= 2
        assert lb2.pending() == 0
        paths = {item["path"] for item in received}
        assert "/startup" in paths
        assert "/event" in paths
    finally:
        server.shutdown()


def test_crash_is_queued_and_sent(tmp_path: Path) -> None:
    server, received, _ = _start_server()
    host, port = server.server_address
    previous = sys.excepthook
    try:
        lb = LogBalloon(
            app_name="TestApp",
            version="0.0.1",
            endpoint=f"http://{host}:{port}",
            data_root=tmp_path / "lb",
            install_excepthook=True,
            flush_interval=60.0,
        )
        lb.start()
        lb.flush(timeout=2.0)  # clear startup first

        try:
            raise ValueError("boom")
        except ValueError:
            exc_type, exc, tb = sys.exc_info()
            lb._excepthook(exc_type, exc, tb)

        crashes = [r for r in received if r["path"] == "/crash"]
        assert len(crashes) == 1
        assert crashes[0]["body"]["exception"] == "ValueError"
        assert "boom" in crashes[0]["body"]["message"]
        assert "ValueError" in crashes[0]["body"]["stacktrace"]

        lb.stop()
        assert sys.excepthook is previous
    finally:
        sys.excepthook = previous
        server.shutdown()
