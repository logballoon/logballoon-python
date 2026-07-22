#!/usr/bin/env python3
"""Minimal LogBalloon client demo."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Allow running without installation: python examples/demo_client.py
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from logballoon import LogBalloon  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="LogBalloon demo client")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8765")
    parser.add_argument("--crash", action="store_true", help="Raise after start (crash demo)")
    args = parser.parse_args()

    lb = LogBalloon(
        app_name="Demo App",
        version="0.1.0",
        endpoint=args.endpoint,
        flush_interval=2.0,
    )
    lb.start()
    print(f"installation_id={lb.installation_id}")
    print(f"pending(before events)={lb.pending()}")

    lb.event("button_click", {"button": "export"})
    lb.event("export_complete", {"rows": 120})

    delivered = lb.flush(timeout=5.0)
    print(f"delivered={delivered} pending={lb.pending()}")

    if args.crash:
        raise RuntimeError("Intentional crash for LogBalloon demo")

    # Give the background worker a moment, then stop cleanly.
    time.sleep(0.5)
    lb.stop()
    print("done")


if __name__ == "__main__":
    main()
