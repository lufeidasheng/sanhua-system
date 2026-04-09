#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import re
import shutil
from datetime import datetime
from pathlib import Path


TARGET_PREFIXES = ['"sysmon."', '"system."', '"memory."', '"ai.ask"']


def main():
    ap = argparse.ArgumentParser(description="稳健修复 decision chain 白名单，加入 system. 前缀")
    ap.add_argument("--root", required=True)
    args = ap.parse_args()

    root = Path(args.root).resolve()
    target = root / "core" / "aicore" / "aicore.py"
    if not target.exists():
        print(f"[ERROR] not found: {target}")
        raise SystemExit(1)

    text = target.read_text(encoding="utf-8", errors="ignore")

    # 先找 allowed_action_prefixes=[...]
    pattern = re.compile(
        r'allowed_action_prefixes\s*=\s*\[(.*?)\]',
        re.DOTALL,
    )
    m = pattern.search(text)
    if not m:
        print("[ERROR] 未找到 allowed_action_prefixes 配置")
        raise SystemExit(1)

    old_block = m.group(0)
    old_inner = m.group(1)

    existing = [x.strip() for x in old_inner.split(",") if x.strip()]
    merged = []
    for item in existing + TARGET_PREFIXES:
        if item not in merged:
            merged.append(item)

    new_block = "allowed_action_prefixes=[" + ", ".join(merged) + "]"

    if old_block == new_block:
        print("[SKIP] 白名单已是目标状态")
        raise SystemExit(0)

    new_text = text.replace(old_block, new_block, 1)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = root / "audit_output" / "fix_backups" / ts / "core" / "aicore"
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup_dir / "aicore.py")

    target.write_text(new_text, encoding="utf-8")

    print("=" * 72)
    print("decision chain whitelist v3 补丁完成")
    print("=" * 72)
    print(f"[PATCHED] {target}")
    print(f"[BACKUP ] {backup_dir / 'aicore.py'}")
    print("新白名单:")
    print("  " + ", ".join(merged))
    print("=" * 72)


if __name__ == "__main__":
    main()
