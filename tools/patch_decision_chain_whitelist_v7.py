#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import re
import shutil
from datetime import datetime
from pathlib import Path


TARGET_PREFIX = '"code_inserter.preview_"'


def backup_file(src: Path, backup_root: Path, root: Path) -> None:
    dst = backup_root / src.relative_to(root)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"[BACKUP ] {dst}")


def patch_allowed_prefixes(text: str) -> str:
    pattern = re.compile(
        r"(allowed_action_prefixes\s*=\s*\[)(.*?)(\])",
        re.DOTALL,
    )
    m = pattern.search(text)
    if not m:
        raise RuntimeError("未找到预期白名单配置")

    head, body, tail = m.group(1), m.group(2), m.group(3)
    if TARGET_PREFIX in body:
        return text

    body_stripped = body.rstrip()
    if body_stripped and not body_stripped.strip().endswith(","):
        body_stripped += ","

    insertion = '\n                "code_inserter.preview_",'
    new_body = body_stripped + insertion + "\n            "

    return text[:m.start()] + head + new_body + tail + text[m.end():]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="patch decision chain whitelist v7")
    parser.add_argument("--root", required=True, help="project root")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    target = root / "core" / "aicore" / "aicore.py"

    old = target.read_text(encoding="utf-8")
    new = patch_allowed_prefixes(old)

    if new == old:
        print("[SKIP] 白名单已包含 code_inserter.preview_")
        raise SystemExit(0)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / "audit_output" / "fix_backups" / ts

    backup_file(target, backup_root, root)
    target.write_text(new, encoding="utf-8")

    print("=" * 72)
    print("decision chain whitelist v7 补丁完成")
    print("=" * 72)
    print(f"[PATCHED] {target}")
    print("新白名单追加:")
    print("  - code_inserter.preview_")
    print("=" * 72)
