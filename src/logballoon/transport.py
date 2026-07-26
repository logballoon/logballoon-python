"""HTTP transport using urllib (stdlib)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any
from urllib.parse import urljoin


class TransportError(Exception):
    """Raised when an HTTP request fails."""


class Transport:
    """Minimal JSON HTTP client."""

    def __init__(
        self,
        endpoint: str,
        timeout: float = 10.0,
        *,
        api_key: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/") + "/"
        self.timeout = timeout
        self._headers = _build_headers(api_key=api_key, headers=headers)

    def _url(self, path: str) -> str:
        return urljoin(self.endpoint, path.lstrip("/"))

    def post(self, path: str, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self._url(path),
            data=body,
            method="POST",
            headers=dict(self._headers),
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
            "user": "/user",
        }.get(kind)
        if path is None:
            raise TransportError(f"Unknown kind: {kind}")
        self.post(path, payload)


def _build_headers(
    *,
    api_key: str | None,
    headers: Mapping[str, str] | None,
) -> dict[str, str]:
    """Merge default headers with optional auth. Caller headers win on conflict."""
    out: dict[str, str] = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
        "User-Agent": "logballoon-python",
    }
    if api_key:
        out["Authorization"] = f"Bearer {api_key}"
    if headers:
        out.update(headers)
    return out
