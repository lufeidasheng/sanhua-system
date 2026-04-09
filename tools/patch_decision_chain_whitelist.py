#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path


def safe_read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def safe_write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def backup_file(src: Path, backup_root: Path, root: Path) -> Path:
    rel = src.relative_to(root)
    dst = backup_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def patch_text(text: str) -> tuple[str, list[str]]:
    steps: list[str] = []

    old = """                    allowed_action_prefixes=[],
"""
    new = """                    allowed_action_prefixes=[
                        "sysmon.",
                        "memory.",
                        "ai.ask",
                    ],
"""
    if old in text:
        text = text.replace(old, new, 1)
        steps.append("收紧 allowed_action_prefixes 为 sysmon./memory./ai.ask")

    # 如果已经改过，就不重复改
    if '"sysmon."' in text and '"memory."' in text and '"ai.ask"' in text and not steps:
        steps.append("白名单已存在，无需重复修改")

    return text, steps


def main():
    ap = argparse.ArgumentParser(description="给 AICore 决策链收紧低风险 action 白名单")
    ap.add_argument("--root", required=True, help="项目根目录")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    target = root / "core" / "aicore" / "aicore.py"

    if not target.exists():
        print(f"[ERROR] 找不到文件：{target}")
        raise SystemExit(1)

    original = safe_read(target)
    patched, steps = patch_text(original)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = backup_file(target, backup_root, root)

    if patched == original:
        print("[SKIP] 未检测到需要修改的内容")
        print(f"[BACKUP] {backup}")
        return

    safe_write(target, patched)

    print("=" * 72)
    print("决策链白名单补丁完成")
    print("=" * 72)
    print(f"[PATCHED] {target}")
    print(f"[BACKUP ] {backup}")
    print("")
    print("本次修改：")
    for s in steps:
        print(f" - {s}")
    print("=" * 72)


if __name__ == "__main__":
    main()
