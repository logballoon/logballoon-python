"""Tkinter contact prompt (stdlib; imported only when ui='tk')."""

from __future__ import annotations

from typing import Any

from logballoon.contact_i18n import (
    DEFAULT_CONTACT_MESSAGE,
    confirm_body,
    contact_strings,
    resolve_lang,
)

DEFAULT_MESSAGE = DEFAULT_CONTACT_MESSAGE


def prompt_contact(
    *,
    mode: str,
    message: str,
    email: str | None = None,
    lang: str | None = None,
) -> dict[str, Any]:
    """Show a modal contact dialog.

    Button labels and window title follow the OS UI language (or ``lang``).
    ``message`` is the body text (caller may override the localized default).

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

    strings = contact_strings(lang)
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        if mode == "confirm":
            return _confirm_dialog(
                root,
                message=message,
                email=email or "",
                strings=strings,
            )
        return _register_dialog(
            root,
            message=message,
            initial=email or "",
            strings=strings,
        )
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def _register_dialog(
    root,
    *,
    message: str,
    initial: str,
    strings: dict[str, str],
) -> dict[str, Any]:
    import tkinter as tk

    result: dict[str, Any] = {"action": "cancel"}

    win = tk.Toplevel(root)
    win.title(strings["title"])
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
    tk.Button(buttons, text=strings["submit"], command=on_submit).pack(
        side="left", padx=4
    )
    tk.Button(buttons, text=strings["skip"], command=on_skip).pack(
        side="left", padx=4
    )

    win.protocol("WM_DELETE_WINDOW", on_skip)
    win.wait_window()
    return result


def _confirm_dialog(
    root,
    *,
    message: str,
    email: str,
    strings: dict[str, str],
) -> dict[str, Any]:
    import tkinter as tk

    result: dict[str, Any] = {"action": "cancel"}

    win = tk.Toplevel(root)
    win.title(strings["title"])
    win.attributes("-topmost", True)
    win.grab_set()

    body = confirm_body(strings, message=message, email=email)
    tk.Label(win, text=body, justify="left", wraplength=360).pack(
        padx=16, pady=(16, 8)
    )

    def set_action(action: str) -> None:
        result.clear()
        result.update({"action": action})
        win.destroy()

    buttons = tk.Frame(win)
    buttons.pack(padx=16, pady=(8, 16))
    tk.Button(buttons, text=strings["ok"], command=lambda: set_action("ok")).pack(
        side="left", padx=4
    )
    tk.Button(
        buttons, text=strings["change"], command=lambda: set_action("change")
    ).pack(side="left", padx=4)
    tk.Button(
        buttons, text=strings["not_now"], command=lambda: set_action("defer")
    ).pack(side="left", padx=4)

    win.protocol("WM_DELETE_WINDOW", lambda: set_action("defer"))
    win.wait_window()
    return result


# Re-export for callers that want to force a pack without importing strings.
__all__ = ["DEFAULT_MESSAGE", "prompt_contact", "resolve_lang"]
