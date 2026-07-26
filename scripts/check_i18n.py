#!/usr/bin/env python3
"""Check that every data-i18n key exists in all language packs."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ("docs/index.html", "docs/protocol.html")
LANGS = ("en", "ja", "zh")


def main() -> int:
    failed = False
    for name in PAGES:
        src = (ROOT / name).read_text(encoding="utf-8")
        used = set(re.findall(r'data-i18n="([^"]+)"', src))
        print(name)
        for lang in LANGS:
            match = re.search(rf"\n      {lang}: \{{(.*?)\n      \}},", src, re.S)
            keys = (
                set(re.findall(r"^\s{8}(\w+):", match.group(1), re.M))
                if match
                else set()
            )
            missing = sorted(used - keys)
            unused = sorted(keys - used)
            status = "ok" if not missing else "MISSING"
            print(f"  {lang}: {status} missing={missing} unused={unused}")
            if missing:
                failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
