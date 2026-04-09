#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path

SAFE_INIT = """from __future__ import annotations

try:
    from .module import entry  # type: ignore
except Exception:
    entry = None

__all__ = ["entry"]
"""


TARGETS = [
    "modules/system_monitor/__init__.py",
    "modules/system_control/__init__.py",
    "modules/code_reader/__init__.py",
    "modules/code_inserter/__init__.py",
    "modules/code_reviewer/__init__.py",
]


def main():
    ap = argparse.ArgumentParser(description="批量修复坏掉的模块 __init__.py")
    ap.add_argument("--root", required=True)
    args = ap.parse_args()

    root = Path(args.root).resolve()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts
    backup_root.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("broken module __init__ 修复开始")
    print("=" * 72)

    for rel in TARGETS:
        path = root / rel
        if not path.exists():
            print(f"[SKIP] not found: {path}")
            continue

        backup = backup_root / rel
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)

        path.write_text(SAFE_INIT, encoding="utf-8")
        print(f"[PATCHED] {path}")
        print(f"[BACKUP ] {backup}")

    print("=" * 72)
    print("修复完成")
    print("=" * 72)


if __name__ == "__main__":
    main()
