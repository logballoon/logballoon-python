"""Data directory and installation_id persistence."""

from __future__ import annotations

import os
import uuid
from pathlib import Path


def data_dir(app_name: str = "logballoon") -> Path:
    """Return a writable per-user data directory."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        path = Path(base) / app_name
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        if xdg:
            path = Path(xdg) / app_name
        else:
            path = Path.home() / ".local" / "share" / app_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_or_create_installation_id(directory: Path | None = None) -> str:
    """Load installation_id from disk, or create one."""
    root = directory or data_dir()
    path = root / "installation_id"
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = str(uuid.uuid4())
    path.write_text(value, encoding="utf-8")
    return value
