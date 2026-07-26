# LogBalloon

Offline-first logging and operations SDK for desktop apps.

**Buffer locally. Deliver reliably.**

Your app keeps working when the network does not. Startup, events, and crashes
go into a local SQLite queue and are delivered to **your own** server when the
link comes back.

- Site: https://logballoon.github.io/logballoon-python/
- Protocol: https://logballoon.github.io/logballoon-python/protocol.html
- PyPI: https://pypi.org/project/logballoon/
- Repo: https://github.com/logballoon/logballoon-python

```bash
pip install logballoon
```

No third-party runtime dependencies — Python stdlib only (`urllib` + `sqlite3`).

---

## Try it in 30 seconds

**No server to set up.** Clone the repo and run one file. It starts a throwaway
receiver on a free port, sends real traffic through the SDK, and prints exactly
what the server received.

```bash
git clone https://github.com/logballoon/logballoon-python
cd logballoon-python
python examples/try_local.py
```

```
receiver listening on http://127.0.0.1:54097 (api key required)

queue pending after flush: 0

--- /startup
{
  "app": "Try LogBalloon",
  "version": "0.0.1",
  "installation_id": "581a1fd5-...",
  "os": "Windows",
  ...
}
--- /event
{ "event": "export_complete", "payload": {"rows": 120, "format": "csv"}, ... }

received: /startup, /event
```

Add `--crash` to also deliver an uncaught exception:

```bash
python examples/try_local.py --crash
```

### Two-terminal version

Closer to real life: a standalone receiver plus a client.

```bash
python examples/demo_server.py      # terminal 1
python examples/demo_client.py      # terminal 2
```

**See the offline queue work:** stop the server, run the client again (items
queue locally), start the server, run the client once more — the backlog flushes.

Other things to try:

| Command | Shows |
|---|---|
| `python examples/demo_client.py --crash` | crash capture via `sys.excepthook` |
| `python examples/demo_client.py --contact` | opt-in Tk contact prompt |
| `python examples/demo_server.py --api-key secret` | endpoint auth (pair with `--api-key secret` on the client) |
| `pip install fastapi uvicorn && python examples/fastapi_server.py` | FastAPI receiver on port 8765 |

---

## Quick start

```python
from logballoon import LogBalloon

lb = LogBalloon(
    app_name="logballoon_test_app",
    version="1.0.0",
    endpoint="http://127.0.0.1:8765",  # your self-hosted server
)
lb.start()
lb.event("export_complete", {"rows": 120, "format": "csv"})
```

That gives you:

- `installation_id` creation and persistence
- startup reporting with an environment snapshot
- custom events
- uncaught exception / crash capture
- SQLite offline queue with retry

`event()` only enqueues — network I/O stays on a background thread, so your UI
never blocks.

## Custom payloads

The **envelope is fixed** for interoperability (`app`, `version`,
`installation_id`, `event`, `timestamp`, …). The **`payload` dict is yours**:

```python
lb.event("job_done", {
    "duration_ms": 842,
    "operator": "A12",
    "batch_id": "2026-07-22-03",
})
```

Full contract: [Protocol page](https://logballoon.github.io/logballoon-python/protocol.html).

## Optional endpoint auth

Auth is **off by default**. When your receiver sits behind a gateway or needs a
shared secret, pass a key:

```python
lb = LogBalloon(
    app_name="logballoon_test_app",
    version="1.0.0",
    endpoint="https://ops.example.com",
    api_key="...",  # sends Authorization: Bearer ...
)
```

Or arbitrary headers (Basic auth, gateway keys, tenant IDs, …):

```python
lb = LogBalloon(
    app_name="logballoon_test_app",
    version="1.0.0",
    endpoint="https://ops.example.com",
    headers={
        "Authorization": "Basic ...",
        "X-Tenant": "lab-a",
    },
)
```

Read secrets from env vars or config files rather than hard-coding them. If both
`api_key` and `headers` set `Authorization`, **`headers` wins**.

## Optional contact prompt

Sometimes you need to reach the person running your app — `installation_id`
alone cannot tell you who they are. LogBalloon can ask for an email, remember
the answer, and deliver it over the same offline queue.

**Nothing happens on import.** The prompt exists only if you turn it on:

```python
lb.start()
lb.enable_contact_prompt(
    ui="tk",             # stdlib Tkinter, imported only when used
    on=("startup",),     # startup only for now
    skip_days=14,        # quiet period after Skip / Not now
    message=None,        # optional; default body follows OS language
    lang=None,           # auto from OS UI language (en / ja / zh); or "ja"
    consent_version=1,
)
```

Behaviour:

- **First run:** enter an email, or Skip
- **Later runs:** confirm the saved address (OK / Change / Not now)
- **Skip or Not now:** stays quiet for `skip_days`
- **Language:** default body and buttons follow the OS UI language (`en` / `ja` /
  `zh`). Override with `lang="ja"` or a custom `message=`
- Email is stored in `contact.json` next to `installation_id` and sent to
  `POST /user` — never mixed into event payloads

Design notes and rationale: [`docs/contact-prompt-spec.md`](docs/contact-prompt-spec.md).

## Self-hosted REST API

LogBalloon does **not** require a SaaS backend. You run the server; it accepts
JSON on four simple routes.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/startup` | Boot + environment |
| `POST` | `/event` | Named event + free-form payload |
| `POST` | `/crash` | Exception + stack trace |
| `POST` | `/user` | Contact email (`register` / `update` / `confirm`) |

Success is any HTTP 2xx. Anything else keeps the item queued for retry, so
delivery is **at-least-once** — make your handlers idempotent if duplicates
matter.

Receivers in this repo:

- `examples/demo_server.py` — stdlib only, optional `--api-key` / `LOGBALLOON_API_KEY`
- `examples/fastapi_server.py` — FastAPI version of the same routes

Full envelope examples: [Protocol page](https://logballoon.github.io/logballoon-python/protocol.html).

## Lightweight defaults

Built for weak PCs and flaky networks:

- small flush batches (`batch_size=20`)
- bounded queue (`max_queue=1000`, drops oldest first)
- exponential backoff on failure (capped by `max_backoff`)
- background delivery only — never on the calling thread

## Client API

| Method | Description |
|---|---|
| `start()` | Enqueue startup and begin background delivery |
| `event(name, payload=None)` | Enqueue a custom event |
| `enable_contact_prompt(...)` | Opt in to the contact (email) dialog |
| `flush(timeout=None)` | Send pending queue items now |
| `stop(flush=True)` | Stop the worker |
| `pending()` | Items still waiting locally |

Constructor options: `app_name`, `version`, `endpoint`, `api_key`, `headers`,
`flush_interval`, `batch_size`, `max_queue`, `max_backoff`, `timeout`,
`install_excepthook`, `data_root`.

## Design

```
App → LogBalloon → SQLite queue → HTTP (urllib) → Your server
                 ↖ retry on recovery ↗
```

## Requirements

- Python 3.10+
- Windows / Linux / macOS (including Raspberry Pi)
- Tkinter only if you enable the contact prompt (`sudo apt install python3-tk` on some Linux distros)

## Development

```bash
pip install -e ".[dev]"
python -m pytest -q
```

CI runs pytest on push/PR via free GitHub Actions (Python 3.10 and 3.12).
