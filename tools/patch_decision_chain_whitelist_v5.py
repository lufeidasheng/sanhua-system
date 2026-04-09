#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import re
import shutil
from datetime import datetime
from pathlib import Path


TARGET_PREFIXES = [
    "sysmon.",
    "memory.",
    "ai.ask",
    "system.",
    "code_reader.",
    "code_reviewer.",
]


def main():
    ap = argparse.ArgumentParser(description="为 AICore 决策链白名单加入 code_reviewer. 前缀")
    ap.add_argument("--root", required=True, help="项目根目录")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    target = root / "core" / "aicore" / "aicore.py"

    if not target.exists():
        print(f"[ERROR] 未找到文件: {target}")
        raise SystemExit(1)

    text = target.read_text(encoding="utf-8", errors="ignore")

    # 兼容：
    # allowed_action_prefixes=[...]
    # allowed_action_prefixes = [...]
    pattern = re.compile(
        r"(allowed_action_prefixes\s*=\s*\[)(.*?)(\])",
        re.DOTALL,
    )
    m = pattern.search(text)
    if not m:
        print("[ERROR] 未找到 allowed_action_prefixes 配置")
        raise SystemExit(1)

    prefix_open = m.group(1)
    inner = m.group(2)
    prefix_close = m.group(3)

    existing = []
    for raw in inner.split(","):
        raw = raw.strip()
        if not raw:
            continue
        # 去掉首尾引号再存成裸值
        val = raw.strip().strip('"').strip("'")
        if val:
            existing.append(val)

    merged = []
    for item in existing + TARGET_PREFIXES:
        if item not in merged:
            merged.append(item)

    new_inner = ", ".join(f'"{x}"' for x in merged)
    new_block = f"{prefix_open}{new_inner}{prefix_close}"
    old_block = m.group(0)

    if old_block == new_block:
        print("[SKIP] 白名单已是目标状态")
        print("当前白名单:")
        for item in merged:
            print(f"  - {item}")
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = root / "audit_output" / "fix_backups" / ts / "core" / "aicore"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / "aicore.py"
    shutil.copy2(target, backup_file)

    new_text = text.replace(old_block, new_block, 1)
    target.write_text(new_text, encoding="utf-8")

    print("=" * 72)
    print("decision chain whitelist v5 补丁完成")
    print("=" * 72)
    print(f"[PATCHED] {target}")
    print(f"[BACKUP ] {backup_file}")
    print("新白名单:")
    for item in merged:
        print(f"  - {item}")
    print("=" * 72)


if __name__ == "__main__":
    main()
