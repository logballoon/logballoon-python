#!/usr/bin/env python3
"""FastAPI receiver sample for local connectivity checks.

Requires: pip install fastapi uvicorn

  uvicorn examples.fastapi_server:app --reload --port 8765

Or:

  python examples/fastapi_server.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LOG_PATH = Path(__file__).resolve().parent / "received_fastapi.jsonl"

try:
    from fastapi import FastAPI, Header, HTTPException, Request
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "FastAPI is not installed. Try: pip install fastapi uvicorn"
    ) from exc

app = FastAPI(title="LogBalloon demo receiver")

# Optional: set to a string to require Authorization: Bearer <key>
REQUIRED_API_KEY: str | None = None


def _check_auth(authorization: str | None, x_api_key: str | None) -> None:
    if not REQUIRED_API_KEY:
        return
    if authorization == f"Bearer {REQUIRED_API_KEY}":
        return
    if x_api_key == REQUIRED_API_KEY:
        return
    raise HTTPException(status_code=401, detail="unauthorized")


async def _accept(
    path: str,
    request: Request,
    authorization: str | None,
    x_api_key: str | None,
) -> dict[str, Any]:
    _check_auth(authorization, x_api_key)
    body = await request.json()
    record = {"path": path, "body": body}
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"[fastapi] {path}: {json.dumps(body, ensure_ascii=False)}")
    return {"ok": True}


@app.post("/startup")
async def startup(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    return await _accept("/startup", request, authorization, x_api_key)


@app.post("/event")
async def event(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    return await _accept("/event", request, authorization, x_api_key)


@app.post("/crash")
async def crash(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    return await _accept("/crash", request, authorization, x_api_key)


@app.post("/user")
async def user(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    return await _accept("/user", request, authorization, x_api_key)


def main() -> None:
    import os

    import uvicorn

    global REQUIRED_API_KEY
    REQUIRED_API_KEY = os.environ.get("LOGBALLOON_API_KEY") or None
    uvicorn.run(app, host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
