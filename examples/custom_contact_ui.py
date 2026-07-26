#!/usr/bin/env python3
"""Framework-independent Contact API example using a terminal as the UI.

Replace input()/print() with widgets, forms, routes, or dialogs from your
framework. The LogBalloon calls stay exactly the same.

Run a receiver first:
    python examples/demo_server.py
Then:
    python examples/custom_contact_ui.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from a clone without installing the package.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from logballoon import LogBalloon  # noqa: E402


def main() -> None:
    lb = LogBalloon(
        app_name="logballoon_contact_example",
        version="0.1.0",
        endpoint="http://127.0.0.1:8765",
    )
    lb.start()

    # Your UI should check this before showing anything.
    if not lb.should_prompt_contact():
        print("The contact prompt is still in its quiet period.")
        lb.stop()
        return

    state = lb.contact_state()
    if state["status"] == "registered" and state.get("email"):
        answer = input(
            f"Use the saved email {state['email']}? "
            "[y]es / [c]hange / [n]ot now: "
        ).strip().lower()
        if answer == "y":
            lb.confirm_contact()
        elif answer == "c":
            email = input("New email: ")
            lb.submit_contact(email)
        else:
            lb.defer_contact()
    else:
        email = input("Contact email (leave blank to skip): ").strip()
        if email:
            lb.submit_contact(email)
        else:
            lb.skip_contact()

    # submit/confirm enqueue /user. flush is optional; the worker also retries.
    lb.flush(timeout=5.0)
    lb.stop()


if __name__ == "__main__":
    main()
