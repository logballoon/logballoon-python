"""HTTP transport using urllib (stdlib)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urljoin


class TransportError(Exception):
    """Raised when an HTTP request fails."""


class Transport:
    """Minimal JSON HTTP client."""

    def __init__(self, endpoint: str, timeout: float = 10.0) -> None:
        self.endpoint = endpoint.rstrip("/") + "/"
        self.timeout = timeout

    def _url(self, path: str) -> str:
        return urljoin(self.endpoint, path.lstrip("/"))

    def post(self, path: str, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self._url(path),
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
                "User-Agent": "logballoon-python",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status = getattr(response, "status", None) or response.getcode()
                if status is None or status >= 400:
                    raise TransportError(f"HTTP {status} for {path}")
                # Drain body so the connection can close cleanly.
                response.read()
        except urllib.error.HTTPError as exc:
            raise TransportError(f"HTTP {exc.code} for {path}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise TransportError(f"Network error for {path}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise TransportError(f"Timeout for {path}") from exc

    def send(self, kind: str, payload: dict[str, Any]) -> None:
        path = {
            "startup": "/startup",
            "event": "/event",
            "crash": "/crash",
        }.get(kind)
        if path is None:
            raise TransportError(f"Unknown kind: {kind}")
        self.post(path, payload)
