"""Lightweight environment snapshot (stdlib only)."""

from __future__ import annotations

import platform
import sys
from typing import Any

from logballoon._version import __version__ as sdk_version


def collect_env(*, app_name: str, version: str, installation_id: str) -> dict[str, Any]:
    """Collect basic runtime environment for startup / crash payloads."""
    return {
        "app": app_name,
        "version": version,
        "sdk_version": sdk_version,
        "installation_id": installation_id,
        "os": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "executable": sys.executable,
    }
