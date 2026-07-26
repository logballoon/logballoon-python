"""Contact-prompt UI strings and locale detection."""

from __future__ import annotations

import locale
import os
import sys
from typing import Any


# Primary language tags we ship. Unknown locales fall back to English.
_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "title": "Contact",
        "message": (
            "May we keep an email so we can contact you if something goes wrong?\n"
            "We only use it when we need to reach you about this app."
        ),
        "submit": "Submit",
        "skip": "Skip",
        "ok": "OK",
        "change": "Change",
        "not_now": "Not now",
        "saved_email": "Saved email: {email}",
        "still_ok": "Is this still OK?",
    },
    "ja": {
        "title": "連絡先",
        "message": (
            "不具合があったときに連絡できるよう、メールアドレスを教えていただけますか？\n"
            "このアプリについてご連絡が必要なときだけ使います。"
        ),
        "submit": "送信",
        "skip": "スキップ",
        "ok": "OK",
        "change": "変更",
        "not_now": "今回は出さない",
        "saved_email": "保存済みのメール: {email}",
        "still_ok": "このまま連絡先として使ってよいですか？",
    },
    "zh": {
        "title": "联系方式",
        "message": (
            "如果出现问题，我们可以用邮件联系你吗？\n"
            "仅在需要就本应用与你联系时使用。"
        ),
        "submit": "提交",
        "skip": "跳过",
        "ok": "确定",
        "change": "更改",
        "not_now": "暂不",
        "saved_email": "已保存的邮箱：{email}",
        "still_ok": "仍然使用这个邮箱吗？",
    },
}

# Windows LANGID primary language → our pack (LANGID & 0x3ff).
_WIN_PRIMARY = {
    0x09: "en",  # English
    0x11: "ja",  # Japanese
    0x04: "zh",  # Chinese (simplified / traditional share primary)
}

# Windows locale.getlocale() often returns names like "Japanese_Japan".
_NAME_TO_LANG = (
    ("japanese", "ja"),
    ("chinese", "zh"),
    ("english", "en"),
)


def detect_ui_lang() -> str:
    """Pick en / ja / zh from the OS UI language. Unknown → en.

    On Windows, the process locale (locale.getlocale) often follows the
    launcher (IDE / English tooling) and can be English even when the user
    runs a Japanese desktop. Prefer GetUserDefaultUILanguage first.
    """
    for tag in _locale_candidates():
        lang = _tag_to_lang(tag)
        if lang:
            return lang
    return "en"


def resolve_lang(lang: str | None) -> str:
    """Return a supported pack name. None / 'auto' → detect."""
    if lang is None or lang == "auto":
        return detect_ui_lang()
    mapped = _tag_to_lang(lang)
    if mapped:
        return mapped
    code = _normalize_tag(lang)
    if code in _STRINGS:
        return code
    return "en"


def contact_strings(lang: str | None = None) -> dict[str, str]:
    """UI copy for the contact prompt."""
    pack = resolve_lang(lang)
    return dict(_STRINGS.get(pack, _STRINGS["en"]))


def default_contact_message(lang: str | None = None) -> str:
    return contact_strings(lang)["message"]


def _normalize_tag(tag: str) -> str:
    return tag.strip().replace("-", "_").lower().split(".")[0]


def _tag_to_lang(tag: str) -> str | None:
    code = _normalize_tag(tag)
    if not code:
        return None
    # ISO-ish: ja, ja_JP, zh_CN, en_US
    if code == "ja" or code.startswith("ja_"):
        return "ja"
    if code == "zh" or code.startswith("zh_"):
        return "zh"
    if code == "en" or code.startswith("en_"):
        return "en"
    # Windows English names: Japanese_Japan, Chinese_China, …
    for name, lang in _NAME_TO_LANG:
        if code == name or code.startswith(name + "_"):
            return lang
    return None


def _locale_candidates() -> list[str]:
    found: list[str] = []

    def _add(tag: str | None) -> None:
        if tag and tag not in found:
            found.append(tag)

    # 1) OS UI language first (most faithful to what the user sees).
    _add(_windows_ui_lang())

    # 2) Explicit env overrides (useful in CI / containers).
    for key in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        raw = os.environ.get(key)
        if not raw:
            continue
        for part in raw.replace(";", ":").split(":"):
            _add(part.strip())

    # 3) Process / default locale (may follow the IDE, not the OS UI).
    _add(_locale_getlocale())
    _add(_locale_getdefaultlocale())

    return found


def _locale_getlocale() -> str | None:
    try:
        lang, _enc = locale.getlocale()
        return lang
    except Exception:  # noqa: BLE001
        return None


def _locale_getdefaultlocale() -> str | None:
    # Deprecated in 3.15 but still useful when getlocale() is unset (common
    # on Windows before setlocale). Suppress the noise; drop when removed.
    getter = getattr(locale, "getdefaultlocale", None)
    if getter is None:
        return None
    try:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            lang, _enc = getter()
        return lang
    except Exception:  # noqa: BLE001
        return None


def _windows_ui_lang() -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        langid = int(ctypes.windll.kernel32.GetUserDefaultUILanguage())
        primary = langid & 0x3FF
        return _WIN_PRIMARY.get(primary)
    except Exception:  # noqa: BLE001
        return None


def confirm_body(strings: dict[str, str], *, message: str, email: str) -> str:
    """Compose the confirm-dialog body from message + saved-email lines."""
    return (
        f"{message}\n\n"
        f"{strings['saved_email'].format(email=email)}\n"
        f"{strings['still_ok']}"
    )


# Keep a stable English default for callers / docs that import the constant.
DEFAULT_CONTACT_MESSAGE = _STRINGS["en"]["message"]


def _as_debug() -> dict[str, Any]:  # pragma: no cover - helper for manual checks
    return {"detected": detect_ui_lang(), "candidates": _locale_candidates()}
