#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path


OLD = """        count_before = _list_count()
        details = []

        if count_before > 0 and not force:
            return {
                "ok": True,
                "reason": "dispatcher_already_has_actions",
                "count_before": count_before,
                "count_after": count_before,
                "details": [],
            }
"""

NEW = """        count_before = _list_count()
        details = []

        current_actions = set()
        try:
            current_actions = set(_normalize_actions(dispatcher.list_actions()))
        except Exception:
            current_actions = set()

        # 只有当核心动作已经齐备时才允许早退
        # 目前我们至少希望看到 ai.* 之外，还要尽量有 sysmon/system/memory 之一
        has_ai = any(str(x).startswith("ai.") for x in current_actions)
        has_sysmon = any(str(x).startswith("sysmon.") for x in current_actions)
        has_system = any(str(x).startswith("system.") for x in current_actions)
        has_memory = any(str(x).startswith("memory.") for x in current_actions)

        core_bootstrap_ready = has_ai and (has_sysmon or has_system or has_memory)

        if count_before > 0 and core_bootstrap_ready and not force:
            return {
                "ok": True,
                "reason": "dispatcher_already_has_core_actions",
                "count_before": count_before,
                "count_after": count_before,
                "details": [],
            }
"""


def main():
    ap = argparse.ArgumentParser(description="修复 aicore 动作引导的早退逻辑")
    ap.add_argument("--root", required=True)
    args = ap.parse_args()

    root = Path(args.root).resolve()
    target = root / "core" / "aicore" / "aicore.py"
    if not target.exists():
        print(f"[ERROR] not found: {target}")
        raise SystemExit(1)

    text = target.read_text(encoding="utf-8", errors="ignore")
    if OLD not in text:
        print("[SKIP] 未找到预期旧代码块，未自动修改。")
        raise SystemExit(0)

    text = text.replace(OLD, NEW, 1)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = root / "audit_output" / "fix_backups" / ts / "core" / "aicore"
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup_dir / "aicore.py")

    target.write_text(text, encoding="utf-8")

    print("=" * 72)
    print("aicore 动作引导 v2 补丁完成")
    print("=" * 72)
    print(f"[PATCHED] {target}")
    print(f"[BACKUP ] {backup_dir / 'aicore.py'}")
    print("=" * 72)


if __name__ == "__main__":
    main()
