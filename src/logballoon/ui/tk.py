"""Tkinter contact prompt (stdlib; imported only when ui='tk')."""

from __future__ import annotations

from typing import Any


from logballoon.contact import DEFAULT_CONTACT_MESSAGE

DEFAULT_MESSAGE = DEFAULT_CONTACT_MESSAGE


def prompt_contact(
    *,
    mode: str,
    message: str,
    email: str | None = None,
) -> dict[str, Any]:
    """Show a modal contact dialog.

    Returns one of:
      {"action": "submit", "email": "..."}
      {"action": "skip"}
      {"action": "ok"}
      {"action": "change"}
      {"action": "defer"}
      {"action": "cancel"}
    """
    try:
        import tkinter as tk
    except ImportError as exc:  # pragma: no cover - depends on OS packages
        raise RuntimeError(
            "tkinter is not available. On Linux try: sudo apt install python3-tk"
        ) from exc

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        if mode == "confirm":
            return _confirm_dialog(root, message=message, email=email or "")
        return _register_dialog(root, message=message, initial=email or "")
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def _register_dialog(root, *, message: str, initial: str) -> dict[str, Any]:
    import tkinter as tk

    # Ask via a small custom dialog so Skip is explicit.
    result: dict[str, Any] = {"action": "cancel"}

    win = tk.Toplevel(root)
    win.title("Contact")
    win.attributes("-topmost", True)
    win.grab_set()

    tk.Label(win, text=message, justify="left", wraplength=360).pack(
        padx=16, pady=(16, 8)
    )
    email_var = tk.StringVar(value=initial)
    entry = tk.Entry(win, textvariable=email_var, width=40)
    entry.pack(padx=16, pady=4)
    entry.focus_set()

    def on_submit() -> None:
        result.clear()
        result.update({"action": "submit", "email": email_var.get()})
        win.destroy()

    def on_skip() -> None:
        result.clear()
        result.update({"action": "skip"})
        win.destroy()

    buttons = tk.Frame(win)
    buttons.pack(padx=16, pady=(8, 16))
    tk.Button(buttons, text="Submit", command=on_submit).pack(side="left", padx=4)
    tk.Button(buttons, text="Skip", command=on_skip).pack(side="left", padx=4)

    win.protocol("WM_DELETE_WINDOW", on_skip)
    win.wait_window()
    return result


def _confirm_dialog(root, *, message: str, email: str) -> dict[str, Any]:
    import tkinter as tk

    result: dict[str, Any] = {"action": "cancel"}

    win = tk.Toplevel(root)
    win.title("Contact")
    win.attributes("-topmost", True)
    win.grab_set()

    body = f"{message}\n\nSaved email: {email}\nIs this still OK?"
    tk.Label(win, text=body, justify="left", wraplength=360).pack(
        padx=16, pady=(16, 8)
    )

    def set_action(action: str) -> None:
        result.clear()
        result.update({"action": action})
        win.destroy()

    buttons = tk.Frame(win)
    buttons.pack(padx=16, pady=(8, 16))
    tk.Button(buttons, text="OK", command=lambda: set_action("ok")).pack(
        side="left", padx=4
    )
    tk.Button(buttons, text="Change", command=lambda: set_action("change")).pack(
        side="left", padx=4
    )
    tk.Button(
        buttons, text="Not now", command=lambda: set_action("defer")
    ).pack(side="left", padx=4)

    win.protocol("WM_DELETE_WINDOW", lambda: set_action("defer"))
    win.wait_window()
    return result
