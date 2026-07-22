"""Public LogBalloon client."""

from __future__ import annotations

import logging
import sys
import threading
import time
import traceback
from typing import Any

from pathlib import Path

from logballoon.env import collect_env
from logballoon.identity import data_dir, get_or_create_installation_id
from logballoon.queue import OfflineQueue
from logballoon.transport import Transport, TransportError

logger = logging.getLogger(__name__)


class LogBalloon:
    """Offline-first operations client for desktop apps."""

    def __init__(
        self,
        *,
        app_name: str,
        version: str,
        endpoint: str,
        flush_interval: float = 5.0,
        batch_size: int = 50,
        timeout: float = 10.0,
        install_excepthook: bool = True,
        data_root: str | Path | None = None,
    ) -> None:
        self.app_name = app_name
        self.version = version
        self.flush_interval = flush_interval
        self.batch_size = batch_size
        self.install_excepthook = install_excepthook

        # data_root: override for tests / custom storage. Default is OS user data dir.
        root = Path(data_root) if data_root is not None else data_dir("logballoon")
        root.mkdir(parents=True, exist_ok=True)
        # Per-app subdirectory keeps queues isolated when multiple apps share the SDK.
        app_dir = root / _safe_name(app_name)
        app_dir.mkdir(parents=True, exist_ok=True)

        self.installation_id = get_or_create_installation_id(app_dir)
        self._queue = OfflineQueue(app_dir / "queue.sqlite3")
        self._transport = Transport(endpoint, timeout=timeout)
        self._env = collect_env(
            app_name=app_name,
            version=version,
            installation_id=self.installation_id,
        )

        self._stop = threading.Event()
        self._wake = threading.Event()
        self._flush_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._started = False
        self._previous_excepthook = None

    def start(self) -> None:
        """Enqueue a startup event and begin background delivery."""
        if self._started:
            return
        self._started = True

        payload = {
            **self._env,
            "timestamp": time.time(),
        }
        self._queue.enqueue("startup", payload)

        if self.install_excepthook:
            self._previous_excepthook = sys.excepthook
            sys.excepthook = self._excepthook

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="logballoon-flush",
            daemon=True,
        )
        self._thread.start()
        self._wake.set()

    def event(self, name: str, payload: dict[str, Any] | None = None) -> None:
        """Enqueue an application event."""
        body = {
            "app": self.app_name,
            "version": self.version,
            "installation_id": self.installation_id,
            "event": name,
            "payload": payload or {},
            "timestamp": time.time(),
        }
        self._queue.enqueue("event", body)
        self._wake.set()

    def flush(self, timeout: float | None = None) -> int:
        """Send queued items now. Returns number of successfully delivered items."""
        deadline = None if timeout is None else time.monotonic() + timeout
        delivered = 0
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                break
            n = self._flush_once()
            delivered += n
            if n == 0:
                break
        return delivered

    def stop(self, *, flush: bool = True, timeout: float = 5.0) -> None:
        """Stop the background worker, optionally flushing first."""
        if flush:
            self.flush(timeout=timeout)
        self._stop.set()
        self._wake.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        if self.install_excepthook and self._previous_excepthook is not None:
            sys.excepthook = self._previous_excepthook
            self._previous_excepthook = None
        self._started = False

    def pending(self) -> int:
        """Number of items waiting in the local queue."""
        return self._queue.count()

    def _excepthook(self, exc_type, exc, tb) -> None:
        try:
            body = {
                **self._env,
                "exception": exc_type.__name__ if exc_type else "Exception",
                "message": str(exc),
                "stacktrace": "".join(traceback.format_exception(exc_type, exc, tb)),
                "timestamp": time.time(),
            }
            self._queue.enqueue("crash", body)
            # Best-effort immediate send; queue remains if offline.
            self._flush_once()
        except Exception:  # noqa: BLE001 — never break the process on crash reporting
            logger.exception("Failed to record crash")
        finally:
            if self._previous_excepthook is not None:
                self._previous_excepthook(exc_type, exc, tb)

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._flush_once()
            except Exception:  # noqa: BLE001
                logger.exception("Flush loop error")
            self._wake.wait(self.flush_interval)
            self._wake.clear()

    def _flush_once(self) -> int:
        # Serialize flush so background worker and flush()/crash path never
        # peek+send the same rows concurrently (which would double-deliver).
        with self._flush_lock:
            items = self._queue.peek(self.batch_size)
            if not items:
                return 0
            delivered = 0
            for item in items:
                self._queue.mark_attempt(item["id"])
                try:
                    self._transport.send(item["kind"], item["payload"])
                except TransportError as exc:
                    logger.debug("Delivery failed (%s): %s", item["kind"], exc)
                    # Stop this pass; keep remaining items for later retry.
                    break
                self._queue.delete(item["id"])
                delivered += 1
            return delivered


def _safe_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name.strip())
    return cleaned or "app"
