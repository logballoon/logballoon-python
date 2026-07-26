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


def _start_server(
    *,
    required_api_key: str | None = None,
) -> tuple[ThreadingHTTPServer, list[dict], threading.Thread]:
    """Tiny local HTTP server that records POSTs."""
    received: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def do_POST(self) -> None:  # noqa: N802
            if required_api_key:
                auth = self.headers.get("Authorization", "")
                x_key = self.headers.get("X-API-Key")
                ok = auth == f"Bearer {required_api_key}" or x_key == required_api_key
                if not ok:
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(b'{"ok":false}')
                    return
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            received.append(
                {
                    "path": self.path,
                    "body": body,
                    "headers": {k: v for k, v in self.headers.items()},
                }
            )
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


def test_transport_sends_api_key_and_custom_headers() -> None:
    server, received, _ = _start_server()
    host, port = server.server_address
    try:
        t = Transport(
            f"http://{host}:{port}",
            timeout=2.0,
            api_key="secret-token",
            headers={"X-Tenant": "lab-a"},
        )
        t.send("event", {"event": "ping"})
        headers = received[0]["headers"]
        assert headers.get("Authorization") == "Bearer secret-token"
        assert headers.get("X-Tenant") == "lab-a"
    finally:
        server.shutdown()


def test_transport_headers_override_api_key() -> None:
    server, received, _ = _start_server()
    host, port = server.server_address
    try:
        t = Transport(
            f"http://{host}:{port}",
            timeout=2.0,
            api_key="ignored",
            headers={"Authorization": "Bearer from-headers"},
        )
        t.send("event", {"event": "ping"})
        assert received[0]["headers"].get("Authorization") == "Bearer from-headers"
    finally:
        server.shutdown()


def test_client_rejects_wrong_api_key(tmp_path: Path) -> None:
    """Wrong API key yields permanent 401 — items are dropped, not retried forever."""
    server, received, _ = _start_server(required_api_key="correct")
    host, port = server.server_address
    try:
        lb = LogBalloon(
            app_name="TestApp",
            version="0.0.1",
            endpoint=f"http://{host}:{port}",
            data_root=tmp_path / "lb",
            install_excepthook=False,
            flush_interval=60.0,
            api_key="wrong",
        )
        lb.start()
        assert lb.flush(timeout=2.0) == 0
        assert lb.pending() == 0
        assert received == []
        lb.stop(flush=False)
    finally:
        server.shutdown()


def test_client_delivers_with_api_key(tmp_path: Path) -> None:
    server, received, _ = _start_server(required_api_key="correct")
    host, port = server.server_address
    try:
        lb = LogBalloon(
            app_name="TestApp",
            version="0.0.1",
            endpoint=f"http://{host}:{port}",
            data_root=tmp_path / "lb",
            install_excepthook=False,
            flush_interval=60.0,
            api_key="correct",
        )
        lb.start()
        lb.event("secured", {"ok": True})
        lb.flush(timeout=3.0)
        assert lb.pending() == 0
        assert any(r["path"] == "/event" for r in received)
        lb.stop()
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
        assert "message_id" in body
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


def test_queue_drops_oldest_when_full(tmp_path: Path) -> None:
    q = OfflineQueue(tmp_path / "q.sqlite3", max_items=3)
    q.enqueue("event", {"n": 1})
    q.enqueue("event", {"n": 2})
    q.enqueue("event", {"n": 3})
    q.enqueue("event", {"n": 4})
    assert q.count() == 3
    nums = [item["payload"]["n"] for item in q.peek(10)]
    assert nums == [2, 3, 4]


def test_queue_prefers_crash_and_user_when_full(tmp_path: Path) -> None:
    q = OfflineQueue(tmp_path / "q.sqlite3", max_items=3)
    q.enqueue("event", {"n": 1})
    q.enqueue("event", {"n": 2})
    q.enqueue("crash", {"n": 3})
    q.enqueue("user", {"n": 4})  # should drop events first
    assert q.count() == 3
    kinds = [item["kind"] for item in q.peek(10)]
    assert "crash" in kinds
    assert "user" in kinds
    assert kinds.count("event") == 1


def test_backoff_grows_then_caps(tmp_path: Path) -> None:
    lb = LogBalloon(
        app_name="TestApp",
        version="0.0.1",
        endpoint="http://127.0.0.1:1",
        install_excepthook=False,
        flush_interval=1.0,
        max_backoff=8.0,
        data_root=tmp_path / "lb",
    )
    lb._fail_streak = 0
    assert lb._wait_seconds() == 1.0
    lb._fail_streak = 1
    assert lb._wait_seconds() == 2.0
    lb._fail_streak = 2
    assert lb._wait_seconds() == 4.0
    lb._fail_streak = 10
    assert lb._wait_seconds() == 8.0


def test_contact_store_register_skip_and_defer(tmp_path: Path) -> None:
    from logballoon.contact import ContactStore, is_plausible_email

    assert is_plausible_email("a@b.c")
    assert not is_plausible_email("nosignal")
    assert not is_plausible_email("   ")

    store = ContactStore(tmp_path / "contact.json")
    assert store.should_prompt()
    store.skip(skip_days=14)
    assert store.load()["status"] == "skipped"
    assert not store.should_prompt()
    # Force skip_until into the past
    data = store.load()
    data["skip_until"] = 1.0
    store.save(data)
    assert store.should_prompt()

    store.register("user@example.com", consent_version=1, skip_days=14)
    assert store.load()["email"] == "user@example.com"
    assert not store.should_prompt()  # quiet after register/OK

    # Expire quiet period → confirm again
    data = store.load()
    data["skip_until"] = 1.0
    store.save(data)
    assert store.should_prompt()

    store.confirm(consent_version=1, skip_days=14)
    assert not store.should_prompt()

    store.defer(skip_days=14)
    assert store.load()["status"] == "registered"
    assert not store.should_prompt()


def test_contact_prompt_register_queues_user(tmp_path: Path) -> None:
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
        lb.flush(timeout=2.0)

        def fake_prompt(*, mode: str, message: str, email: str | None = None, **_kwargs):
            assert mode == "register"
            return {"action": "submit", "email": "dev@example.com"}

        lb.enable_contact_prompt(ui="custom", prompt_fn=fake_prompt)
        lb.flush(timeout=3.0)

        users = [r for r in received if r["path"] == "/user"]
        assert len(users) == 1
        body = users[0]["body"]
        assert body["email"] == "dev@example.com"
        assert body["action"] == "register"
        assert body["consent_version"] == 1
        assert (tmp_path / "lb" / "TestApp" / "contact.json").exists()
        lb.stop()
    finally:
        server.shutdown()


def test_contact_prompt_confirm_and_offline_queue(tmp_path: Path) -> None:
    calls: list[str] = []

    def fake_prompt(*, mode: str, message: str, email: str | None = None, **_kwargs):
        calls.append(mode)
        if mode == "confirm":
            return {"action": "ok"}
        return {"action": "skip"}

    lb = LogBalloon(
        app_name="TestApp",
        version="0.0.1",
        endpoint="http://127.0.0.1:1",
        data_root=tmp_path / "lb",
        install_excepthook=False,
        flush_interval=60.0,
    )
    # Seed registered state
    from logballoon.contact import ContactStore

    store = ContactStore(tmp_path / "lb" / "TestApp" / "contact.json")
    store.register("kept@example.com", consent_version=1, skip_days=14)
    # Expire quiet period so confirm is due.
    data = store.load()
    data["skip_until"] = 1.0
    store.save(data)

    lb.start()
    lb.enable_contact_prompt(ui="custom", prompt_fn=fake_prompt)
    assert calls == ["confirm"]
    assert not store.should_prompt()  # OK applies quiet period
    assert lb.flush(timeout=1.0) == 0  # offline
    assert lb.pending() >= 2  # startup + user confirm
    kinds = [item["kind"] for item in lb._queue.peek(10)]
    assert "user" in kinds
    user_item = next(i for i in lb._queue.peek(10) if i["kind"] == "user")
    assert user_item["payload"]["action"] == "confirm"
    assert user_item["payload"]["email"] == "kept@example.com"
    assert "message_id" in user_item["payload"]
    lb.stop(flush=False)


def test_contact_prompt_skip_does_not_enqueue(tmp_path: Path) -> None:
    lb = LogBalloon(
        app_name="TestApp",
        version="0.0.1",
        endpoint="http://127.0.0.1:1",
        data_root=tmp_path / "lb",
        install_excepthook=False,
        flush_interval=60.0,
    )
    lb.start()
    before = lb.pending()
    lb.enable_contact_prompt(
        ui="custom",
        prompt_fn=lambda **kwargs: {"action": "skip"},
    )
    assert lb.pending() == before  # no /user
    from logballoon.contact import ContactStore

    store = ContactStore(tmp_path / "lb" / "TestApp" / "contact.json")
    assert store.load()["status"] == "skipped"
    assert not store.should_prompt()
    lb.stop(flush=False)


def test_contact_i18n_detects_and_resolves(monkeypatch) -> None:
    from logballoon.contact_i18n import (
        contact_strings,
        default_contact_message,
        detect_ui_lang,
        resolve_lang,
    )

    monkeypatch.setenv("LC_ALL", "ja_JP.UTF-8")
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    monkeypatch.delenv("LANG", raising=False)
    monkeypatch.delenv("LANGUAGE", raising=False)
    monkeypatch.setattr(
        "logballoon.contact_i18n._locale_getlocale", lambda: None
    )
    monkeypatch.setattr(
        "logballoon.contact_i18n._locale_getdefaultlocale", lambda: None
    )
    monkeypatch.setattr(
        "logballoon.contact_i18n._windows_ui_lang", lambda: None
    )
    assert detect_ui_lang() == "ja"
    assert "メール" in default_contact_message()
    assert contact_strings("ja")["submit"] == "送信"
    assert contact_strings("zh")["skip"] == "跳过"
    assert resolve_lang("ja-JP") == "ja"
    assert resolve_lang("fr") == "en"


def test_contact_prompt_uses_explicit_lang(tmp_path: Path) -> None:
    seen: dict[str, str] = {}

    def fake_prompt(*, mode: str, message: str, email: str | None = None, lang: str = "en"):
        seen["lang"] = lang
        seen["message"] = message
        return {"action": "skip"}

    lb = LogBalloon(
        app_name="TestApp",
        version="0.0.1",
        endpoint="http://127.0.0.1:1",
        data_root=tmp_path / "lb",
        install_excepthook=False,
        flush_interval=60.0,
    )
    lb.start()
    lb.enable_contact_prompt(ui="custom", lang="ja", prompt_fn=fake_prompt)
    assert seen["lang"] == "ja"
    assert "メール" in seen["message"]
    lb.stop(flush=False)


def test_permanent_http_error_drops_item(tmp_path: Path) -> None:
    """401/4xx permanent errors should not clog the queue forever."""
    received: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            received.append({"path": self.path, "body": body})
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"ok":false}')

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
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
        lb.event("will_fail", {"x": 1})
        # Permanent 401 → items dropped (delivered count is 0, pending 0)
        assert lb.flush(timeout=3.0) == 0
        assert lb.pending() == 0
        assert len(received) >= 1
        lb.stop(flush=False)
    finally:
        server.shutdown()


def test_max_attempts_drops_poison(tmp_path: Path) -> None:
    lb = LogBalloon(
        app_name="TestApp",
        version="0.0.1",
        endpoint="http://127.0.0.1:1",
        data_root=tmp_path / "lb",
        install_excepthook=False,
        flush_interval=60.0,
        max_attempts=2,
    )
    lb.start()
    # Force high attempt counts on everything currently queued.
    for item in lb._queue.peek(20):
        for _ in range(3):
            lb._queue.mark_attempt(item["id"])
    assert lb.flush(timeout=2.0) == 0
    assert lb.pending() == 0
    lb.stop(flush=False)
