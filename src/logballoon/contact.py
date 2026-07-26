"""Local contact (email) persistence for optional contact prompts."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

# Re-export English default for backward-compatible imports.
from logballoon.contact_i18n import DEFAULT_CONTACT_MESSAGE  # noqa: F401


def is_plausible_email(value: str) -> bool:
    """Lenient check: non-empty after strip and contains '@'."""
    text = value.strip()
    return bool(text) and "@" in text


class ContactStore:
    """Read/write contact.json beside installation_id."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"status": "unset"}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"status": "unset"}
        if not isinstance(data, dict):
            return {"status": "unset"}
        status = data.get("status") or "unset"
        data["status"] = status
        return data

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def should_prompt(self, *, now: float | None = None) -> bool:
        """Return True when a contact dialog should be shown."""
        now = time.time() if now is None else now
        state = self.load()
        status = state.get("status", "unset")
        skip_until = state.get("skip_until")
        if skip_until is not None:
            try:
                if now < float(skip_until):
                    return False
            except (TypeError, ValueError):
                pass
        if status in {"unset", "skipped", "registered"}:
            return True
        return True

    def register(self, email: str, *, consent_version: int) -> dict[str, Any]:
        now = time.time()
        data = {
            "status": "registered",
            "email": email.strip(),
            "updated_at": now,
            "last_confirmed_at": now,
            "skip_until": None,
            "consent_version": consent_version,
        }
        self.save(data)
        return data

    def update_email(self, email: str, *, consent_version: int) -> dict[str, Any]:
        return self.register(email, consent_version=consent_version)

    def confirm(self, *, consent_version: int) -> dict[str, Any]:
        state = self.load()
        email = str(state.get("email") or "").strip()
        now = time.time()
        data = {
            "status": "registered",
            "email": email,
            "updated_at": state.get("updated_at", now),
            "last_confirmed_at": now,
            "skip_until": None,
            "consent_version": consent_version,
        }
        self.save(data)
        return data

    def skip(self, *, skip_days: float) -> dict[str, Any]:
        now = time.time()
        data = {
            "status": "skipped",
            "email": None,
            "updated_at": now,
            "last_confirmed_at": None,
            "skip_until": now + skip_days * 86400.0,
            "consent_version": None,
        }
        self.save(data)
        return data

    def defer(self, *, skip_days: float) -> dict[str, Any]:
        """Keep registered email; hide prompt until skip_until."""
        state = self.load()
        now = time.time()
        data = {
            "status": "registered",
            "email": state.get("email"),
            "updated_at": state.get("updated_at", now),
            "last_confirmed_at": state.get("last_confirmed_at"),
            "skip_until": now + skip_days * 86400.0,
            "consent_version": state.get("consent_version"),
        }
        self.save(data)
        return data
