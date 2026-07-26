"""Public LogBalloon client."""

from __future__ import annotations

import logging
import sys
import threading
import time
import traceback
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Callable

from logballoon.contact import ContactStore, is_plausible_email
from logballoon.contact_i18n import default_contact_message, resolve_lang
from logballoon.env import collect_env
from logballoon.identity import data_dir, get_or_create_installation_id
from logballoon.queue import OfflineQueue
from logballoon.transport import Transport, TransportError

logger = logging.getLogger(__name__)

ContactPromptFn = Callable[..., dict[str, Any]]


class LogBalloon:
    """Offline-first operations client for desktop apps."""

    def __init__(
        self,
        *,
        app_name: str,
        version: str,
        endpoint: str,
        flush_interval: float = 5.0,
        batch_size: int = 20,
        max_queue: int = 1000,
        max_backoff: float = 120.0,
        max_attempts: int = 40,
        timeout: float = 5.0,
        install_excepthook: bool = True,
        data_root: str | Path | None = None,
        api_key: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.app_name = app_name
        self.version = version
        self.flush_interval = flush_interval
        self.batch_size = batch_size
        self.max_backoff = max_backoff
        self.max_attempts = max_attempts
        self.install_excepthook = install_excepthook

        # data_root: override for tests / custom storage. Default is OS user data dir.
        root = Path(data_root) if data_root is not None else data_dir("logballoon")
        root.mkdir(parents=True, exist_ok=True)
        # Per-app subdirectory keeps queues isolated when multiple apps share the SDK.
        self._app_dir = root / _safe_name(app_name)
        self._app_dir.mkdir(parents=True, exist_ok=True)

        self.installation_id = get_or_create_installation_id(self._app_dir)
        self._queue = OfflineQueue(self._app_dir / "queue.sqlite3", max_items=max_queue)
        self._transport = Transport(
            endpoint,
            timeout=timeout,
            api_key=api_key,
            headers=headers,
        )
        self._env = collect_env(
            app_name=app_name,
            version=version,
            installation_id=self.installation_id,
        )

        self._stop = threading.Event()
        self._wake = threading.Event()
        self._flush_lock = threading.Lock()
        self._fail_streak = 0
        self._thread: threading.Thread | None = None
        self._started = False
        self._previous_excepthook = None

        # Contact prompt is opt-in; untouched until enable_contact_prompt().
        self._contact: ContactStore | None = None
        self._contact_ui: str | None = None
        self._contact_on: tuple[str, ...] = ()
        self._contact_skip_days = 14.0
        self._contact_message: str | None = None
        self._contact_lang: str = "en"
        self._contact_consent_version = 1
        self._contact_prompt_fn: ContactPromptFn | None = None

    def start(self) -> None:
        """Enqueue a startup event and begin background delivery."""
        if self._started:
            return
        self._started = True

        payload = self._stamp({
            **self._env,
            "timestamp": time.time(),
        })
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

        if "startup" in self._contact_on:
            self._maybe_prompt_contact()

    def enable_contact_prompt(
        self,
        *,
        ui: str,
        on: Sequence[str] = ("startup",),
        skip_days: float = 14,
        message: str | None = None,
        lang: str | None = None,
        consent_version: int = 1,
        prompt_fn: ContactPromptFn | None = None,
    ) -> None:
        """Opt in to the contact (email) prompt. Does nothing until called.

        ``ui`` must be ``\"tk\"`` for the built-in dialog, or pass ``prompt_fn``
        for tests / custom UIs (``ui`` may then be any label such as ``\"custom\"``).

        ``lang`` defaults to auto-detect from the OS UI language (``en`` / ``ja`` /
        ``zh``). Pass an explicit code to override. ``message`` overrides only the
        body text; button labels still follow ``lang``.

        Call this on the UI / main thread when using ``ui=\"tk\"`` — the dialog is
        modal. After OK / register / Skip / Not now, the prompt stays quiet for
        ``skip_days`` (default 14).
        """
        triggers = tuple(on)
        for name in triggers:
            if name not in {"startup"}:
                raise ValueError(
                    f"Unsupported contact trigger {name!r} in MVP "
                    "(only 'startup' is supported)"
                )
        if prompt_fn is None and ui != "tk":
            raise ValueError(
                f"Unsupported contact UI {ui!r}. "
                "Use ui='tk' or pass prompt_fn= for a custom dialog."
            )
        if skip_days < 0:
            raise ValueError("skip_days must be >= 0")

        self._contact = ContactStore(self._app_dir / "contact.json")
        self._contact_ui = ui
        self._contact_on = triggers
        self._contact_skip_days = float(skip_days)
        self._contact_lang = resolve_lang(lang)
        self._contact_message = message
        self._contact_consent_version = int(consent_version)
        self._contact_prompt_fn = prompt_fn

        if self._started and "startup" in self._contact_on:
            self._maybe_prompt_contact()

    def event(self, name: str, payload: dict[str, Any] | None = None) -> None:
        """Enqueue an application event (non-blocking)."""
        body = self._stamp({
            "app": self.app_name,
            "version": self.version,
            "installation_id": self.installation_id,
            "event": name,
            "payload": payload or {},
            "timestamp": time.time(),
        })
        self._queue.enqueue("event", body)
        # Wake the worker, but do not send on the caller thread.
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

    def _stamp(self, body: dict[str, Any]) -> dict[str, Any]:
        """Attach a stable message_id for at-least-once idempotency on the server."""
        if "message_id" not in body:
            body = {**body, "message_id": str(uuid.uuid4())}
        return body

    def _maybe_prompt_contact(self) -> None:
        if self._contact is None:
            return
        if not self._contact.should_prompt():
            return
        try:
            self._run_contact_prompt()
        except Exception:  # noqa: BLE001 — never break the app for a prompt
            logger.exception("Contact prompt failed")

    def _run_contact_prompt(self) -> None:
        assert self._contact is not None
        state = self._contact.load()
        status = state.get("status", "unset")
        message = self._contact_message or default_contact_message(self._contact_lang)
        quiet = self._contact_skip_days

        if status == "registered" and state.get("email"):
            result = self._invoke_contact_ui(
                mode="confirm",
                message=message,
                email=str(state["email"]),
            )
            action = result.get("action")
            if action == "ok":
                self._contact.confirm(
                    consent_version=self._contact_consent_version,
                    skip_days=quiet,
                )
                self._enqueue_user(
                    email=str(state["email"]),
                    action="confirm",
                )
            elif action == "change":
                self._prompt_register(message=message, initial=str(state["email"]))
            elif action in {"defer", "cancel", "skip"}:
                self._contact.defer(skip_days=quiet)
            return

        self._prompt_register(message=message, initial="")

    def _prompt_register(self, *, message: str, initial: str) -> None:
        assert self._contact is not None
        quiet = self._contact_skip_days
        while True:
            result = self._invoke_contact_ui(
                mode="register",
                message=message,
                email=initial,
            )
            action = result.get("action")
            if action in {"skip", "cancel", "defer"}:
                self._contact.skip(skip_days=quiet)
                return
            if action != "submit":
                self._contact.skip(skip_days=quiet)
                return
            email = str(result.get("email") or "")
            if not is_plausible_email(email):
                # Re-show with the bad value so the user can fix it.
                initial = email.strip()
                continue
            existing = self._contact.load()
            action_name = (
                "update"
                if existing.get("status") == "registered" and existing.get("email")
                else "register"
            )
            if action_name == "update":
                self._contact.update_email(
                    email,
                    consent_version=self._contact_consent_version,
                    skip_days=quiet,
                )
            else:
                self._contact.register(
                    email,
                    consent_version=self._contact_consent_version,
                    skip_days=quiet,
                )
            self._enqueue_user(email=email.strip(), action=action_name)
            return

    def _invoke_contact_ui(
        self,
        *,
        mode: str,
        message: str,
        email: str,
    ) -> dict[str, Any]:
        if self._contact_prompt_fn is not None:
            return self._contact_prompt_fn(
                mode=mode,
                message=message,
                email=email,
                lang=self._contact_lang,
            )
        if self._contact_ui == "tk":
            from logballoon.ui import tk as tk_ui

            return tk_ui.prompt_contact(
                mode=mode,
                message=message,
                email=email,
                lang=self._contact_lang,
            )
        raise RuntimeError(f"No contact UI available for {self._contact_ui!r}")

    def _enqueue_user(self, *, email: str, action: str) -> None:
        body = self._stamp({
            **self._env,
            "email": email.strip(),
            "action": action,
            "consent_version": self._contact_consent_version,
            "timestamp": time.time(),
        })
        self._queue.enqueue("user", body)
        self._wake.set()

    def _excepthook(self, exc_type, exc, tb) -> None:
        try:
            body = self._stamp({
                **self._env,
                "exception": exc_type.__name__ if exc_type else "Exception",
                "message": str(exc),
                "stacktrace": "".join(traceback.format_exception(exc_type, exc, tb)),
                "timestamp": time.time(),
            })
            self._queue.enqueue("crash", body)
            # Best-effort immediate send; queue remains if offline.
            self._flush_once()
        except Exception:  # noqa: BLE001 — never break the process on crash reporting
            logger.exception("Failed to record crash")
        finally:
            if self._previous_excepthook is not None:
                self._previous_excepthook(exc_type, exc, tb)

    def _wait_seconds(self) -> float:
        if self._fail_streak <= 0:
            return self.flush_interval
        # Exponential backoff capped for weak PCs / flaky networks.
        wait = self.flush_interval * (2 ** min(self._fail_streak, 6))
        return min(wait, self.max_backoff)

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                delivered = self._flush_once()
                pending = self._queue.count()
                if delivered > 0:
                    self._fail_streak = 0
                elif pending > 0:
                    self._fail_streak += 1
                else:
                    self._fail_streak = 0
            except Exception:  # noqa: BLE001
                logger.exception("Flush loop error")
                self._fail_streak += 1
            self._wake.wait(self._wait_seconds())
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
                attempts = int(item["attempts"]) + 1
                if attempts > self.max_attempts:
                    logger.warning(
                        "Dropping %s after %s attempts (max_attempts=%s)",
                        item["kind"],
                        attempts,
                        self.max_attempts,
                    )
                    self._queue.delete(item["id"])
                    continue
                try:
                    self._transport.send(item["kind"], item["payload"])
                except TransportError as exc:
                    if exc.permanent:
                        logger.warning(
                            "Dropping %s after permanent error: %s",
                            item["kind"],
                            exc,
                        )
                        self._queue.delete(item["id"])
                        continue
                    logger.debug("Delivery failed (%s): %s", item["kind"], exc)
                    # Transient failure: stop this pass; retry later.
                    break
                self._queue.delete(item["id"])
                delivered += 1
            return delivered


def _safe_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name.strip())
    return cleaned or "app"
