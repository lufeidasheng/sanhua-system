#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description="扩展决策链白名单，加入 system. 前缀")
    ap.add_argument("--root", required=True)
    args = ap.parse_args()

    root = Path(args.root).resolve()
    target = root / "core" / "aicore" / "aicore.py"
    if not target.exists():
        print(f"[ERROR] not found: {target}")
        raise SystemExit(1)

    text = target.read_text(encoding="utf-8", errors="ignore")

    old = """                allowed_action_prefixes=["sysmon.", "memory.", "ai.ask"],"""
    new = """                allowed_action_prefixes=["sysmon.", "system.", "memory.", "ai.ask"],"""

    if new in text:
        print("[SKIP] 白名单已包含 system.")
        raise SystemExit(0)

    if old not in text:
        print("[ERROR] 未找到预期白名单配置")
        raise SystemExit(1)

    text = text.replace(old, new, 1)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = root / "audit_output" / "fix_backups" / ts / "core" / "aicore"
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup_dir / "aicore.py")

    target.write_text(text, encoding="utf-8")

    print("=" * 72)
    print("decision chain whitelist v2 补丁完成")
    print("=" * 72)
    print(f"[PATCHED] {target}")
    print(f"[BACKUP ] {backup_dir / 'aicore.py'}")
    print("=" * 72)


if __name__ == "__main__":
    main()
