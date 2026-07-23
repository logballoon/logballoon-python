# LogBalloon

Offline-first logging and operations SDK for desktop apps.

**Buffer locally. Deliver reliably.**

- Site: https://logballoon.github.io/logballoon-python/
- PyPI: https://pypi.org/project/logballoon/
- Repo: https://github.com/logballoon/logballoon-python

## Install

```bash
pip install logballoon
```

From this repository:

```bash
pip install -e ".[dev]"
```

## Quick start

```python
from logballoon import LogBalloon

lb = LogBalloon(
    app_name="FFT Analyzer",
    version="1.0.0",
    endpoint="http://127.0.0.1:8765",  # your self-hosted server
)
lb.start()
lb.event("export_complete", {"rows": 120, "format": "csv"})
```

With that you get:

- `installation_id` creation and persistence
- startup reporting
- custom events
- uncaught exception / crash capture
- SQLite offline queue + retry

**No third-party runtime dependencies** (Python stdlib only).

## Custom payloads

The **envelope is fixed** for interoperability (`app`, `version`, `installation_id`, `event`, `timestamp`, …).

The **`payload` dict is yours** — add any fields your product needs:

```python
lb.event("job_done", {
    "duration_ms": 842,
    "operator": "A12",
    "batch_id": "2026-07-22-03",
})
```

## Self-hosted REST API

LogBalloon does **not** require a SaaS backend. You run the server and accept JSON on simple REST routes:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/startup` | Boot + environment |
| `POST` | `/event` | Named event + free-form payload |
| `POST` | `/crash` | Exception + stack trace |

Point `endpoint=` at your host. A minimal demo receiver is included:

```bash
python examples/demo_server.py
python examples/demo_client.py
```

Offline check: stop the server, run the client (events queue), start the server, run again (queued items flush).

## Client API

| Method | Description |
|---|---|
| `start()` | Enqueue startup and begin background delivery |
| `event(name, payload=None)` | Enqueue a custom event |
| `flush(timeout=None)` | Send pending queue items now |
| `stop(flush=True)` | Stop the worker |

## Design

```
App → LogBalloon → SQLite queue → HTTP (urllib) → Your server
                 ↖ retry on recovery ↗
```

## Requirements

- Python 3.10+
- Windows / Linux / macOS (including Raspberry Pi)

## Development

```bash
pip install -e ".[dev]"
python -m pytest -q
```

CI runs pytest on push/PR via free GitHub Actions (Python 3.10 and 3.12).
